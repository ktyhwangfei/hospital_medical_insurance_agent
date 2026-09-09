"""健康运营问题库 PG 存储活库冒烟 — #45（DDL/去重/过滤分页）
+ #50（事件表 DDL / 乐观锁流转 / 时间线）。

验证 ops_findings / ops_finding_events 表 DDL（CREATE+ALTER 双写幂等）、
fingerprint 唯一索引 ON CONFLICT 去重累计、条件 UPDATE 乐观锁流转与
事件留痕在真实 PostgreSQL 上成立。
环境依赖: PostgreSQL（127.0.0.1:5432/hospital_mcp，与生产同构）；不可用时整组 skip。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data_platform.storage.ops.ops_postgres import PostgresOpsFindingStorage
from src.domain.ops.models import (
    FindingDraft,
    FindingRevisionConflictError,
    OpsAssetType,
    OpsFindingEvent,
    OpsFindingEventType,
    OpsFindingNotFoundError,
    OpsFindingStatus,
    OpsSeverity,
    new_finding_event_id,
)

T0 = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=10)
SMOKE_ASSET = "ops_pg_smoke_source"


def _pg_ready() -> bool:
    try:
        from src.data_platform.storage.postgresql.client import PostgreSQLClient

        client = PostgreSQLClient()
        client.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_ready(), reason="PostgreSQL 不可用，跳过活库冒烟")


@pytest.fixture
def storage() -> PostgresOpsFindingStorage:
    return PostgresOpsFindingStorage()


@pytest.fixture(autouse=True)
def _cleanup(storage: PostgresOpsFindingStorage):
    yield
    client = storage._get_client()
    client.execute(
        """
        DELETE FROM ops_finding_events WHERE finding_id IN (
            SELECT finding_id FROM ops_findings WHERE asset_id = %s
        )
        """,
        (SMOKE_ASSET,),
    )
    client.execute("DELETE FROM ops_findings WHERE asset_id = %s", (SMOKE_ASSET,))


def _draft(check_id: str, severity: OpsSeverity, payload: dict) -> FindingDraft:
    return FindingDraft(
        asset_type=OpsAssetType.DATA,
        asset_id=SMOKE_ASSET,
        check_id=check_id,
        severity=severity,
        payload=payload,
    )


def test_schema_idempotent_and_upsert_dedup(storage: PostgresOpsFindingStorage):
    # 二次构造触发 ensure_schema 重跑（CREATE IF NOT EXISTS + ALTER IF NOT EXISTS 幂等）
    PostgresOpsFindingStorage(client=storage._get_client())._get_client()

    first = storage.upsert_finding(
        _draft("data_sync_failed", OpsSeverity.WARNING, {"problem": "sync_job_degraded"}),
        seen_at=T0,
    )
    assert first.status == OpsFindingStatus.OPEN
    assert first.occurrence_count == 1

    second = storage.upsert_finding(
        _draft("data_sync_failed", OpsSeverity.CRITICAL, {"problem": "sync_job_failed"}),
        seen_at=T1,
    )
    # fingerprint 唯一索引 + ON CONFLICT：同一问题累计而非新增行
    assert second.finding_id == first.finding_id
    assert second.occurrence_count == 2
    assert second.revision == 2
    assert second.first_seen_at == T0
    assert second.last_seen_at == T1
    assert second.severity is OpsSeverity.CRITICAL  # 严重度随最新证据刷新


def test_filters_and_ordering(storage: PostgresOpsFindingStorage):
    # 活库与开发环境共享：断言收窄到 SMOKE_ASSET 作用域，不受真实运维数据影响
    storage.upsert_finding(
        _draft("data_sync_failed", OpsSeverity.WARNING, {"problem": "sync_job_degraded"}),
        seen_at=T0,
    )
    storage.upsert_finding(
        _draft("data_source_down", OpsSeverity.CRITICAL, {"safe_probe_message": "连接超时"}),
        seen_at=T0,
    )

    critical = storage.list_findings(severity=OpsSeverity.CRITICAL, asset_type=OpsAssetType.DATA)
    smoke_critical = [f for f in critical.items if f.asset_id == SMOKE_ASSET]
    assert len(smoke_critical) == 1
    assert smoke_critical[0].check_id == "data_source_down"
    assert smoke_critical[0].payload["safe_probe_message"] == "连接超时"

    all_open = storage.list_findings(status=OpsFindingStatus.OPEN, page=1, page_size=1)
    assert len(all_open.items) == 1  # 分页切片生效
    assert all_open.items[0].severity is OpsSeverity.CRITICAL  # critical 排序在前
    smoke_open_total = sum(
        1 for page_num in (1, 2)
        for f in storage.list_findings(
            status=OpsFindingStatus.OPEN, page=page_num, page_size=100,
        ).items
        if f.asset_id == SMOKE_ASSET
    )
    assert smoke_open_total == 2
    assert not any(
        f.asset_id == SMOKE_ASSET
        for f in storage.list_findings(status=OpsFindingStatus.RESOLVED, page=1, page_size=100).items
    )


def _event(finding_id: str, event_type: OpsFindingEventType, reason: str | None,
           created_at: datetime) -> OpsFindingEvent:
    return OpsFindingEvent(
        event_id=new_finding_event_id(),
        finding_id=finding_id,
        event_type=event_type,
        actor="ops-admin-1",
        reason=reason,
        created_at=created_at,
    )


def test_lifecycle_transition_and_events_on_live_pg(storage: PostgresOpsFindingStorage):
    finding = storage.upsert_finding(
        _draft("data_sync_failed", OpsSeverity.WARNING, {"problem": "sync_job_degraded"}),
        seen_at=T0,
    )

    # 乐观锁流转：ignore 后 status/revision 变化，事件落 ops_finding_events
    ignored = storage.transition_finding(
        finding.finding_id,
        expected_revision=finding.revision,
        new_status=OpsFindingStatus.IGNORED,
        event=_event(finding.finding_id, OpsFindingEventType.IGNORED, "排期维护", T1),
    )
    assert ignored.status == OpsFindingStatus.IGNORED
    assert ignored.revision == finding.revision + 1
    events = storage.list_finding_events(finding.finding_id)
    assert [e.event_type for e in events] == [OpsFindingEventType.IGNORED]
    assert events[0].reason == "排期维护"

    # reopen 回到 open，时间线追加第二条
    reopened = storage.transition_finding(
        finding.finding_id,
        expected_revision=ignored.revision,
        new_status=OpsFindingStatus.OPEN,
        event=_event(finding.finding_id, OpsFindingEventType.REOPENED, None, T1 + timedelta(minutes=1)),
    )
    assert reopened.status == OpsFindingStatus.OPEN
    assert [e.event_type for e in storage.list_finding_events(finding.finding_id)] == [
        OpsFindingEventType.IGNORED, OpsFindingEventType.REOPENED,
    ]
    assert storage.get_finding(finding.finding_id).revision == reopened.revision


def test_stale_revision_conflicts_on_live_pg(storage: PostgresOpsFindingStorage):
    finding = storage.upsert_finding(
        _draft("data_source_down", OpsSeverity.CRITICAL, {"safe_probe_message": "连接超时"}),
        seen_at=T0,
    )
    storage.upsert_finding(
        _draft("data_source_down", OpsSeverity.CRITICAL, {"safe_probe_message": "连接超时"}),
        seen_at=T1,
    )  # 复现使 revision+1
    with pytest.raises(FindingRevisionConflictError):
        storage.transition_finding(
            finding.finding_id,
            expected_revision=finding.revision,
            new_status=OpsFindingStatus.IGNORED,
            event=_event(finding.finding_id, OpsFindingEventType.IGNORED, "过期", T1),
        )
    # 冲突不产生半写：状态未变、无事件
    assert storage.get_finding(finding.finding_id).status == OpsFindingStatus.OPEN
    assert storage.list_finding_events(finding.finding_id) == []

    with pytest.raises(OpsFindingNotFoundError):
        storage.get_finding("no-such-finding")
