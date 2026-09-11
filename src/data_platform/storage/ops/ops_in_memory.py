"""健康运营问题库内存存储（开发/测试；USE_MEMORY_STORAGE=1）。"""
from __future__ import annotations

import threading
from copy import deepcopy
from datetime import datetime, timezone

from src.domain.ops.models import (
    FindingDraft,
    FindingRevisionConflictError,
    OpsAssetType,
    OpsCheckerError,
    OpsFinding,
    OpsFindingEvent,
    OpsFindingNotFoundError,
    OpsFindingPage,
    OpsFindingStatus,
    OpsInspectionNotFoundError,
    OpsInspectionRun,
    OpsInspectionScheduleState,
    OpsInspectionStatus,
    OpsInspectionTrigger,
    OpsRemediationRun,
    OpsSeverity,
    finding_fingerprint,
    new_finding_id,
    new_inspection_id,
)

_SEVERITY_RANK = {
    OpsSeverity.CRITICAL: 0,
    OpsSeverity.WARNING: 1,
    OpsSeverity.INFO: 2,
}

# 调度行初值：epoch 即「立即到期」，与 PG 首部署 bootstrap(next_run_at=now) 语义一致
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class InMemoryOpsFindingStorage:
    """dict + 深拷贝隔离；fingerprint 唯一，排序与 PG 一致（severity → last_seen_at 倒序）。"""

    def __init__(self) -> None:
        self._findings: dict[str, OpsFinding] = {}  # fingerprint → OpsFinding
        self._events: dict[str, list[OpsFindingEvent]] = {}  # finding_id → 事件（升序追加）
        self._runs: dict[str, list[OpsRemediationRun]] = {}  # finding_id → 修复留痕（升序追加）
        self._inspections: dict[str, OpsInspectionRun] = {}  # inspection_id → 运行留痕
        self._schedule = OpsInspectionScheduleState(next_run_at=_EPOCH)
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

    def insert_remediation_run(self, run: OpsRemediationRun) -> OpsRemediationRun:
        with self._lock:
            stored = run.model_copy(deep=True)
            self._runs.setdefault(run.finding_id, []).append(stored)
            return stored.model_copy(deep=True)

    def list_remediation_runs(self, finding_id: str) -> list[OpsRemediationRun]:
        with self._lock:
            runs = self._runs.get(finding_id, [])
            return [run.model_copy(deep=True) for run in runs]

    def save_diagnosis(self, finding_id: str, diagnosis: dict) -> OpsFinding:
        with self._lock:
            current = self.get_finding(finding_id)  # 不存在则抛 NotFound
            updated = current.model_copy(update={"diagnosis": deepcopy(diagnosis)})
            self._findings[current.fingerprint] = updated
            return updated.model_copy(deep=True)

    # ── #52 定时巡检调度：claim 抢占 + 运行留痕（互斥语义与 PG 一致）──

    def claim_inspection(
        self,
        now: datetime,
        *,
        trigger_source: OpsInspectionTrigger,
        triggered_by: str,
    ) -> OpsInspectionRun | None:
        with self._lock:
            if self._schedule.active_inspection_id is not None:
                return None
            if (
                trigger_source is not OpsInspectionTrigger.MANUAL
                and self._schedule.next_run_at > now
            ):
                return None
            run = OpsInspectionRun(
                inspection_id=new_inspection_id(),
                trigger_source=trigger_source,
                status=OpsInspectionStatus.RUNNING,
                triggered_by=triggered_by,
                started_at=now,
            )
            self._inspections[run.inspection_id] = run
            self._schedule = self._schedule.model_copy(
                update={"active_inspection_id": run.inspection_id}
            )
            return run.model_copy(deep=True)

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
        with self._lock:
            current = self._inspections.get(inspection_id)
            if current is None:
                raise OpsInspectionNotFoundError(inspection_id)
            updated = current.model_copy(update={
                "status": status,
                "finished_at": finished_at,
                "finding_count": finding_count,
                "new_finding_count": new_finding_count,
                "checker_errors": [error.model_copy(deep=True) for error in checker_errors],
            })
            self._inspections[inspection_id] = updated
            if self._schedule.active_inspection_id == inspection_id:
                self._schedule = self._schedule.model_copy(update={
                    "active_inspection_id": None,
                    "next_run_at": next_run_at,
                })
            return updated.model_copy(deep=True)

    def get_inspection(self, inspection_id: str) -> OpsInspectionRun:
        with self._lock:
            run = self._inspections.get(inspection_id)
            if run is None:
                raise OpsInspectionNotFoundError(inspection_id)
            return run.model_copy(deep=True)

    def get_latest_inspection(self) -> OpsInspectionRun | None:
        with self._lock:
            if not self._inspections:
                return None
            latest = max(
                self._inspections.values(),
                key=lambda run: (run.started_at, run.inspection_id),
            )
            return latest.model_copy(deep=True)

    def get_inspection_schedule(self) -> OpsInspectionScheduleState:
        with self._lock:
            return self._schedule.model_copy(deep=True)
