"""健康运营服务 — 巡检编排、问题查询与生命周期流转（#45 P0 + #50）。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from pydantic import BaseModel, Field

from src.data_platform.storage.ops.ops_ports import OpsFindingStorage
from src.domain.ops.models import (
    InvalidFindingTransitionError,
    OpsAssetType,
    OpsFinding,
    OpsFindingDetail,
    OpsFindingEvent,
    OpsFindingEventType,
    OpsFindingPage,
    OpsFindingStatus,
    OpsSeverity,
    new_finding_event_id,
)
from src.runtime.ops.checkers import OPS_CHECKS, GovernanceStatusReader

logger = logging.getLogger(__name__)


class CheckerError(BaseModel):
    """单检查器执行失败记录（不中断整次巡检）。"""

    check_id: str
    message: str


class OpsInspectionResult(BaseModel):
    """一次手动巡检的结果快照。"""

    checked_at: datetime
    check_count: int = Field(ge=1)
    finding_count: int = Field(ge=0)
    findings: list[OpsFinding]
    checker_errors: list[CheckerError]


class OpsHealthService:
    """巡检编排：逐检查器只读取数 → 问题库 fingerprint 去重落库。"""

    def __init__(
        self,
        storage: OpsFindingStorage,
        reader_factory: Callable[[], GovernanceStatusReader],
    ) -> None:
        self._storage = storage
        self._reader_factory = reader_factory

    def run_inspection(self, *, now: datetime | None = None) -> OpsInspectionResult:
        checked_at = now or datetime.now(timezone.utc)
        reader = self._reader_factory()
        findings: list[OpsFinding] = []
        errors: list[CheckerError] = []
        for spec in OPS_CHECKS:
            try:
                drafts = spec.runner(reader, checked_at)
            except Exception as exc:  # 检查器只读，单点故障不拖垮整次巡检
                logger.warning("ops 检查器 %s 执行失败: %s", spec.check_id, exc)
                errors.append(CheckerError(check_id=spec.check_id, message=str(exc)))
                continue
            for draft in drafts:
                findings.append(self._storage.upsert_finding(draft, seen_at=checked_at))
        return OpsInspectionResult(
            checked_at=checked_at,
            check_count=len(OPS_CHECKS),
            finding_count=len(findings),
            findings=findings,
            checker_errors=errors,
        )

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
        """单条问题详情：当前状态 + 生命周期事件时间线。"""
        finding = self._storage.get_finding(finding_id)
        return OpsFindingDetail(finding=finding, events=self._storage.list_finding_events(finding_id))

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
