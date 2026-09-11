"""健康运营问题库内存存储单元测试 — #45（去重/累计/过滤/排序）
+ #50（详情 / 乐观锁流转 / 事件时间线）+ #53（修复留痕）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data_platform.storage.ops.ops_in_memory import InMemoryOpsFindingStorage
from src.domain.ops.models import (
    FindingDraft,
    FindingRevisionConflictError,
    InvalidFindingTransitionError,
    OpsAssetType,
    OpsFindingEvent,
    OpsFindingEventType,
    OpsFindingNotFoundError,
    OpsFindingStatus,
    OpsRemediationRun,
    OpsSeverity,
    RemediationRiskLevel,
    RemediationRunStatus,
    VerificationResult,
    finding_fingerprint,
    new_finding_event_id,
    new_remediation_run_id,
)

T0 = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=10)


def _draft(check_id: str = "data_sync_failed", severity: OpsSeverity = OpsSeverity.WARNING,
           asset_id: str = "bjybdb") -> FindingDraft:
    return FindingDraft(
        asset_type=OpsAssetType.DATA,
        asset_id=asset_id,
        check_id=check_id,
        severity=severity,
        payload={"problem": "sync_job_failed"},
    )


class TestUpsertDedup:
    def test_repeat_inspection_same_fingerprint_accumulates(self):
        store = InMemoryOpsFindingStorage()
        first = store.upsert_finding(_draft(), seen_at=T0)
        second = store.upsert_finding(_draft(), seen_at=T1)
        assert second.finding_id == first.finding_id
        assert second.fingerprint == finding_fingerprint(OpsAssetType.DATA, "bjybdb", "data_sync_failed")
        assert second.occurrence_count == 2
        assert second.revision == 2
        assert second.last_seen_at == T1
        assert second.first_seen_at == T0  # 首见时间不随复现漂移
        assert second.status is OpsFindingStatus.OPEN

    def test_distinct_problems_distinct_findings(self):
        store = InMemoryOpsFindingStorage()
        store.upsert_finding(_draft(check_id="data_sync_failed"), seen_at=T0)
        store.upsert_finding(_draft(check_id="data_source_down", severity=OpsSeverity.CRITICAL), seen_at=T0)
        page = store.list_findings()
        assert page.total == 2
        assert {f.check_id for f in page.items} == {"data_sync_failed", "data_source_down"}

    def test_severity_refreshes_on_recurrence(self):
        store = InMemoryOpsFindingStorage()
        store.upsert_finding(_draft(severity=OpsSeverity.WARNING), seen_at=T0)
        refreshed = store.upsert_finding(_draft(severity=OpsSeverity.CRITICAL), seen_at=T1)
        assert refreshed.severity is OpsSeverity.CRITICAL


class TestListFilters:
    @pytest.fixture
    def seeded(self):
        store = InMemoryOpsFindingStorage()
        store.upsert_finding(_draft(check_id="data_sync_failed", severity=OpsSeverity.WARNING), seen_at=T0)
        store.upsert_finding(_draft(check_id="data_source_down", severity=OpsSeverity.CRITICAL), seen_at=T1)
        store.upsert_finding(_draft(check_id="data_source_down", severity=OpsSeverity.CRITICAL, asset_id="his"), seen_at=T0)
        return store

    def test_filter_by_severity(self, seeded):
        page = seeded.list_findings(severity=OpsSeverity.CRITICAL)
        assert page.total == 2
        assert all(f.severity is OpsSeverity.CRITICAL for f in page.items)

    def test_filter_by_asset_type(self, seeded):
        page = seeded.list_findings(asset_type=OpsAssetType.DATA)
        assert page.total == 3
        assert seeded.list_findings(asset_type=OpsAssetType.SKILL).total == 0

    def test_severity_orders_critical_first(self, seeded):
        items = seeded.list_findings().items
        assert items[0].severity is OpsSeverity.CRITICAL

    def test_pagination_slices(self, seeded):
        page = seeded.list_findings(page=2, page_size=2)
        assert page.total == 3
        assert len(page.items) == 1
        assert page.page == 2

    def test_status_filter_excludes_missing_status(self, seeded):
        assert seeded.list_findings(status=OpsFindingStatus.RESOLVED).total == 0
        assert seeded.list_findings(status=OpsFindingStatus.OPEN).total == 3


def _event(finding_id: str, event_type: OpsFindingEventType, reason: str | None = None,
           created_at: datetime = T1) -> OpsFindingEvent:
    return OpsFindingEvent(
        event_id=new_finding_event_id(),
        finding_id=finding_id,
        event_type=event_type,
        actor="ops-admin-1",
        reason=reason,
        created_at=created_at,
    )


class TestLifecycle:
    """#50：get / transition（乐观锁 + 事件留痕）/ 事件时间线。"""

    @pytest.fixture
    def store_with_finding(self):
        store = InMemoryOpsFindingStorage()
        finding = store.upsert_finding(_draft(), seen_at=T0)
        return store, finding

    def test_get_finding_unknown_raises(self):
        store = InMemoryOpsFindingStorage()
        with pytest.raises(OpsFindingNotFoundError):
            store.get_finding("no-such-id")

    def test_get_finding_returns_current_state(self, store_with_finding):
        store, finding = store_with_finding
        assert store.get_finding(finding.finding_id) == finding

    def test_transition_updates_status_and_appends_event(self, store_with_finding):
        store, finding = store_with_finding
        event = _event(finding.finding_id, OpsFindingEventType.IGNORED, reason="排期维护")
        updated = store.transition_finding(
            finding.finding_id,
            expected_revision=finding.revision,
            new_status=OpsFindingStatus.IGNORED,
            event=event,
        )
        assert updated.status is OpsFindingStatus.IGNORED
        assert updated.revision == finding.revision + 1
        assert store.get_finding(finding.finding_id).status is OpsFindingStatus.IGNORED
        events = store.list_finding_events(finding.finding_id)
        assert [e.event_type for e in events] == [OpsFindingEventType.IGNORED]
        assert events[0].reason == "排期维护"

    def test_transition_with_stale_revision_raises_conflict(self, store_with_finding):
        store, finding = store_with_finding
        store.upsert_finding(_draft(), seen_at=T1)  # 复现巡检使 revision+1
        with pytest.raises(FindingRevisionConflictError):
            store.transition_finding(
                finding.finding_id,
                expected_revision=finding.revision,
                new_status=OpsFindingStatus.IGNORED,
                event=_event(finding.finding_id, OpsFindingEventType.IGNORED, "过期"),
            )

    def test_transition_unknown_finding_raises_not_found(self):
        store = InMemoryOpsFindingStorage()
        with pytest.raises(OpsFindingNotFoundError):
            store.transition_finding(
                "no-such-id",
                expected_revision=1,
                new_status=OpsFindingStatus.IGNORED,
                event=_event("no-such-id", OpsFindingEventType.IGNORED, "x"),
            )

    def test_events_timeline_keeps_insertion_order(self, store_with_finding):
        store, finding = store_with_finding
        store.transition_finding(
            finding.finding_id,
            expected_revision=finding.revision,
            new_status=OpsFindingStatus.IGNORED,
            event=_event(finding.finding_id, OpsFindingEventType.IGNORED, "先忽略", created_at=T1),
        )
        store.transition_finding(
            finding.finding_id,
            expected_revision=finding.revision + 1,
            new_status=OpsFindingStatus.OPEN,
            event=_event(finding.finding_id, OpsFindingEventType.REOPENED, created_at=T1 + timedelta(minutes=1)),
        )
        assert [e.event_type for e in store.list_finding_events(finding.finding_id)] == [
            OpsFindingEventType.IGNORED, OpsFindingEventType.REOPENED,
        ]

    def test_events_isolated_between_findings(self):
        store = InMemoryOpsFindingStorage()
        first = store.upsert_finding(_draft(), seen_at=T0)
        second = store.upsert_finding(_draft(check_id="data_source_down", severity=OpsSeverity.CRITICAL), seen_at=T0)
        store.transition_finding(
            first.finding_id,
            expected_revision=first.revision,
            new_status=OpsFindingStatus.IGNORED,
            event=_event(first.finding_id, OpsFindingEventType.IGNORED, "只影响第一条"),
        )
        assert store.list_finding_events(second.finding_id) == []


class TestServiceLifecycle:
    """#50 服务层状态机：非法流转在服务层拦截，存储只管乐观锁。"""

    @pytest.fixture
    def service_with_finding(self):
        from src.runtime.ops.service import OpsHealthService

        store = InMemoryOpsFindingStorage()
        finding = store.upsert_finding(_draft(), seen_at=T0)
        service = OpsHealthService(store, lambda: _NoopReader())
        return service, finding

    def test_ignore_then_reopen_roundtrip(self, service_with_finding):
        service, finding = service_with_finding
        ignored = service.ignore_finding(
            finding.finding_id, expected_revision=finding.revision,
            reason="已知误报", actor="ops-admin-1",
        )
        assert ignored.finding.status is OpsFindingStatus.IGNORED
        reopened = service.reopen_finding(
            finding.finding_id, expected_revision=ignored.finding.revision, actor="ops-admin-1",
        )
        assert reopened.finding.status is OpsFindingStatus.OPEN
        assert [e.event_type for e in reopened.events] == [
            OpsFindingEventType.IGNORED, OpsFindingEventType.REOPENED,
        ]

    def test_ignore_on_ignored_raises_invalid_transition(self, service_with_finding):
        service, finding = service_with_finding
        service.ignore_finding(
            finding.finding_id, expected_revision=finding.revision,
            reason="一次", actor="ops-admin-1",
        )
        with pytest.raises(InvalidFindingTransitionError):
            service.ignore_finding(
                finding.finding_id, expected_revision=2,
                reason="两次", actor="ops-admin-1",
            )

    def test_reopen_on_open_raises_invalid_transition(self, service_with_finding):
        service, finding = service_with_finding
        with pytest.raises(InvalidFindingTransitionError):
            service.reopen_finding(finding.finding_id, expected_revision=1, actor="ops-admin-1")

    def test_get_detail_unknown_propagates_not_found(self, service_with_finding):
        service, _ = service_with_finding
        with pytest.raises(OpsFindingNotFoundError):
            service.get_finding_detail("no-such-id")


class _NoopReader:
    """生命周期操作不触达巡检读取面。"""

    def list_sources(self):
        return []

    def get_job(self, source_id):
        raise LookupError(source_id)


def _run(finding_id: str, *, action: str = "retry_data_sync",
         status: RemediationRunStatus = RemediationRunStatus.SUCCEEDED,
         verification: VerificationResult | None = VerificationResult.PASSED,
         created_at: datetime = T1) -> OpsRemediationRun:
    return OpsRemediationRun(
        run_id=new_remediation_run_id(),
        finding_id=finding_id,
        action=action,
        risk_level=RemediationRiskLevel.L1,
        status=status,
        before_evidence={"job_status": "failed"},
        after_evidence={"job_status": "running"},
        verification_result=verification,
        created_by="ops-admin-1",
        created_at=created_at,
    )


class TestRemediationRuns:
    """#53：修复留痕追加与时间线读取。"""

    def test_insert_returns_run_and_lists_in_order(self):
        store = InMemoryOpsFindingStorage()
        finding = store.upsert_finding(_draft(), seen_at=T0)
        first = store.insert_remediation_run(_run(finding.finding_id, created_at=T1))
        second = store.insert_remediation_run(
            _run(finding.finding_id, created_at=T1 + timedelta(minutes=1)),
        )
        runs = store.list_remediation_runs(finding.finding_id)
        assert [r.run_id for r in runs] == [first.run_id, second.run_id]
        assert runs[0].verification_result is VerificationResult.PASSED
        assert runs[0].risk_level is RemediationRiskLevel.L1

    def test_runs_isolated_between_findings(self):
        store = InMemoryOpsFindingStorage()
        first = store.upsert_finding(_draft(), seen_at=T0)
        second = store.upsert_finding(_draft(check_id="data_source_down"), seen_at=T0)
        store.insert_remediation_run(_run(first.finding_id))
        assert store.list_remediation_runs(second.finding_id) == []

    def test_runs_of_unknown_finding_empty(self):
        store = InMemoryOpsFindingStorage()
        assert store.list_remediation_runs("no-such-id") == []
