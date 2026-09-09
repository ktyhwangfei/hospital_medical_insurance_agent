"""健康运营问题库存储端口 — ports/adapter，默认 PostgreSQL，可回退内存。"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.domain.ops.models import (
    FindingDraft,
    OpsAssetType,
    OpsFinding,
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
