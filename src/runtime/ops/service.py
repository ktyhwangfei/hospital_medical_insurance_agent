"""健康运营服务 — 巡检编排与问题查询（issue #45 P0）。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from pydantic import BaseModel, Field

from src.data_platform.storage.ops.ops_ports import OpsFindingStorage
from src.domain.ops.models import (
    OpsAssetType,
    OpsFinding,
    OpsFindingPage,
    OpsFindingStatus,
    OpsSeverity,
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
