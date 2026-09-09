"""健康运营问题库内存存储（开发/测试；USE_MEMORY_STORAGE=1）。"""
from __future__ import annotations

import threading
from datetime import datetime

from src.domain.ops.models import (
    FindingDraft,
    FindingRevisionConflictError,
    OpsAssetType,
    OpsFinding,
    OpsFindingEvent,
    OpsFindingNotFoundError,
    OpsFindingPage,
    OpsFindingStatus,
    OpsSeverity,
    finding_fingerprint,
    new_finding_id,
)

_SEVERITY_RANK = {
    OpsSeverity.CRITICAL: 0,
    OpsSeverity.WARNING: 1,
    OpsSeverity.INFO: 2,
}


class InMemoryOpsFindingStorage:
    """dict + 深拷贝隔离；fingerprint 唯一，排序与 PG 一致（severity → last_seen_at 倒序）。"""

    def __init__(self) -> None:
        self._findings: dict[str, OpsFinding] = {}  # fingerprint → OpsFinding
        self._events: dict[str, list[OpsFindingEvent]] = {}  # finding_id → 事件（升序追加）
        self._lock = threading.RLock()

    def upsert_finding(self, draft: FindingDraft, *, seen_at: datetime) -> OpsFinding:
        fingerprint = finding_fingerprint(draft.asset_type, draft.asset_id, draft.check_id)
        with self._lock:
            current = self._findings.get(fingerprint)
            if current is None:
                created = OpsFinding(
                    finding_id=new_finding_id(),
                    asset_type=draft.asset_type,
                    asset_id=draft.asset_id,
                    check_id=draft.check_id,
                    severity=draft.severity,
                    status=OpsFindingStatus.OPEN,
                    fingerprint=fingerprint,
                    payload=draft.payload,
                    first_seen_at=seen_at,
                    last_seen_at=seen_at,
                    occurrence_count=1,
                    revision=1,
                )
                self._findings[fingerprint] = created
                return created.model_copy(deep=True)
            updated = current.model_copy(update={
                "severity": draft.severity,
                "payload": draft.payload,
                "last_seen_at": seen_at,
                "occurrence_count": current.occurrence_count + 1,
                "revision": current.revision + 1,
            })
            self._findings[fingerprint] = updated
            return updated.model_copy(deep=True)

    def list_findings(
        self,
        *,
        status: OpsFindingStatus | None = None,
        severity: OpsSeverity | None = None,
        asset_type: OpsAssetType | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> OpsFindingPage:
        with self._lock:
            matched = [
                finding for finding in self._findings.values()
                if (status is None or finding.status == status)
                and (severity is None or finding.severity == severity)
                and (asset_type is None or finding.asset_type == asset_type)
            ]
        matched.sort(key=lambda f: (_SEVERITY_RANK[f.severity], -f.last_seen_at.timestamp()))
        total = len(matched)
        start = (page - 1) * page_size
        return OpsFindingPage(
            items=[f.model_copy(deep=True) for f in matched[start:start + page_size]],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_finding(self, finding_id: str) -> OpsFinding:
        with self._lock:
            for finding in self._findings.values():
                if finding.finding_id == finding_id:
                    return finding.model_copy(deep=True)
        raise OpsFindingNotFoundError(finding_id)

    def transition_finding(
        self,
        finding_id: str,
        *,
        expected_revision: int,
        new_status: OpsFindingStatus,
        event: OpsFindingEvent,
    ) -> OpsFinding:
        with self._lock:
            current = self.get_finding(finding_id)  # 不存在则抛 NotFound
            if current.revision != expected_revision:
                raise FindingRevisionConflictError(finding_id, expected_revision, current.revision)
            fingerprint = current.fingerprint
            updated = current.model_copy(update={
                "status": new_status,
                "revision": current.revision + 1,
            })
            self._findings[fingerprint] = updated
            self._events.setdefault(finding_id, []).append(event.model_copy(deep=True))
            return updated.model_copy(deep=True)

    def list_finding_events(self, finding_id: str) -> list[OpsFindingEvent]:
        with self._lock:
            events = self._events.get(finding_id, [])
            return [event.model_copy(deep=True) for event in events]
