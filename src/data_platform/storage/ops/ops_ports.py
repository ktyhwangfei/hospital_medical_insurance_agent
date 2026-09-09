"""健康运营问题库存储端口 — ports/adapter，默认 PostgreSQL，可回退内存。"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.domain.ops.models import (
    FindingDraft,
    OpsAssetType,
    OpsFinding,
    OpsFindingEvent,
    OpsFindingPage,
    OpsFindingStatus,
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
