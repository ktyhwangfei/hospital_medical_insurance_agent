"""健康运营问题库内存存储单元测试 — issue #45（去重/累计/过滤/排序）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data_platform.storage.ops.ops_in_memory import InMemoryOpsFindingStorage
from src.domain.ops.models import (
    FindingDraft,
    OpsAssetType,
    OpsFindingStatus,
    OpsSeverity,
    finding_fingerprint,
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
