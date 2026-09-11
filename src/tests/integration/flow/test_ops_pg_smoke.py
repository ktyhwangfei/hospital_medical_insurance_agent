"""健康运营问题库 PG 存储活库冒烟 — #45（DDL/去重/过滤分页）
+ #50（事件表 DDL / 乐观锁流转 / 时间线）+ #53（修复留痕表 DDL / 闭环流转）
+ #52（巡检运行表 DDL / claim 抢占互斥 / 调度行推进）。

验证 ops_findings / ops_finding_events / ops_remediation_runs /
ops_inspections / ops_inspection_schedule 表 DDL（CREATE+ALTER 双写幂等）、
fingerprint 唯一索引 ON CONFLICT 去重累计、条件 UPDATE 乐观锁流转、
L1 修复留痕与 resolved 闭环、FOR UPDATE SKIP LOCKED 并发抢占不重复执行
在真实 PostgreSQL 上成立。
环境依赖: PostgreSQL（127.0.0.1:5432/hospital_mcp，与生产同构）；不可用时整组 skip。
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from src.data_platform.storage.ops.ops_postgres import PostgresOpsFindingStorage
from src.domain.ops.models import (
    FindingDraft,
    FindingRevisionConflictError,
    OpsAssetType,
    OpsCheckerError,
    OpsFindingEvent,
    OpsFindingEventType,
    OpsFindingNotFoundError,
    OpsFindingStatus,
    OpsInspectionStatus,
    OpsInspectionTrigger,
    OpsSeverity,
    RemediationRiskLevel,
    RemediationRunStatus,
    VerificationResult,
    new_finding_event_id,
)
from src.runtime.ops.remediation import RemediationActionOutcome, RemediationSpec
from src.runtime.ops.service import OpsHealthService

T0 = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=10)
SMOKE_ASSET = "ops_pg_smoke_source"
SMOKE_INSPECTOR = "ops-pg-smoke"
# 本 pytest 会话开始时刻：#52 冒烟行的删除下界（roundtrip 行 triggered_by 是
# system:ops-scheduler/ops-admin-1，无法按 triggered_by 过滤；且 run_manual
# 会产生未来时间戳行——不删会永久占据 get_latest_inspection 排序首位）
SESSION_STARTED_AT = datetime.now(timezone.utc)


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
        DELETE FROM ops_remediation_runs WHERE finding_id IN (
            SELECT finding_id FROM ops_findings WHERE asset_id = %s
        )
        """,
        (SMOKE_ASSET,),
    )
    client.execute(
        """
        DELETE FROM ops_finding_events WHERE finding_id IN (
            SELECT finding_id FROM ops_findings WHERE asset_id = %s
        )
        """,
        (SMOKE_ASSET,),
    )
    client.execute("DELETE FROM ops_findings WHERE asset_id = %s", (SMOKE_ASSET,))
    # #52：清掉本次会话产生的全部巡检留痕，并把调度行无条件复位为立即到期
    # （测试中途失败可能留下 running 占位；带 active IS NULL 守卫的复位治不了
    # 这种卡死，反而让后续所有 claim 永久返回 None）
    client.execute(
        "DELETE FROM ops_inspections WHERE triggered_by = %s OR started_at >= %s",
        (SMOKE_INSPECTOR, SESSION_STARTED_AT),
    )
    client.execute(
        """UPDATE ops_inspection_schedule
           SET next_run_at = NOW(), active_inspection_id = NULL, updated_at = NOW()
           WHERE schedule_id = 1""",
    )


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


class _HealthyReader:
    """闭环验证用读取面：同资产任务健康，检查器不再产出问题。"""

    def list_sources(self):
        return []

    def get_job(self, source_id):
        raise LookupError(source_id)


def test_remediation_closed_loop_on_live_pg(storage: PostgresOpsFindingStorage):
    """#53：修复留痕表 DDL + 验证通过 → resolved 事件 + run 行在活库成立。"""
    # 首次 _get_client 已 ensure 全部三表 DDL（含 ops_remediation_runs 幂等重跑）
    PostgresOpsFindingStorage(client=storage._get_client())._get_client()

    finding = storage.upsert_finding(
        _draft("data_sync_failed", OpsSeverity.CRITICAL, {"problem": "sync_job_failed"}),
        seen_at=T0,
    )
    outcome = RemediationActionOutcome(
        executed=True,
        before_evidence={"job_status": "failed"},
        after_evidence={"job_status": "running"},
    )
    whitelist = (RemediationSpec(
        action_id="retry_data_sync",
        check_id="data_sync_failed",
        risk_level=RemediationRiskLevel.L1,
        description="重试门诊同步（冒烟）",
        executor=lambda f, actor: outcome,
    ),)
    service = OpsHealthService(storage, lambda: _HealthyReader(), whitelist)

    result = service.remediate_finding(
        finding.finding_id, expected_revision=finding.revision, actor="ops-admin-1",
    )

    # 留痕行落 ops_remediation_runs，证据与验证结果完整往返
    runs = storage.list_remediation_runs(finding.finding_id)
    assert [r.run_id for r in runs] == [result.run.run_id]
    assert runs[0].status is RemediationRunStatus.SUCCEEDED
    assert runs[0].verification_result is VerificationResult.PASSED
    assert runs[0].before_evidence == {"job_status": "failed"}
    assert runs[0].after_evidence == {"job_status": "running"}
    assert runs[0].risk_level is RemediationRiskLevel.L1
    # 验证通过 → open → resolved + 事件留痕
    assert storage.get_finding(finding.finding_id).status == OpsFindingStatus.RESOLVED
    events = storage.list_finding_events(finding.finding_id)
    assert [e.event_type for e in events] == [OpsFindingEventType.RESOLVED]
    assert "retry_data_sync" in events[0].reason
    # 详情聚合含修复留痕时间线
    assert [r.run_id for r in service.get_finding_detail(finding.finding_id).remediations] == [
        result.run.run_id,
    ]


def test_diagnosis_report_persisted_on_live_pg(storage: PostgresOpsFindingStorage):
    """#51：诊断报告覆盖落库（JSONB 往返）、不动 status/revision；重诊覆盖旧报告。"""
    import json as _json

    from src.model_service.models import ModelResponse, TokenUsage
    from src.runtime.ops.diagnosis import OpsDiagnosisService

    finding = storage.upsert_finding(
        _draft("data_sync_failed", OpsSeverity.CRITICAL, {
            "problem": "sync_job_failed", "job_status": "failed",
        }),
        seen_at=T0,
    )

    class _FixedGateway:
        def __init__(self, content: str):
            self.content = content

        def generate(self, messages, model_type, scene, **kwargs):
            return ModelResponse(
                content=self.content,
                model_name="fake-diag-model",
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
                finish_reason="stop",
            )

    service = OpsDiagnosisService(
        storage, lambda: _FixedGateway(_json.dumps({
            "root_cause": "同步连接失败",
            "citations": ["E1"],
            "uncertainties": [],
            "actions": [
                {"level": "L1", "description": "重试同步", "citation_ids": ["E1"]},
            ],
        })),
        evidence_collector=lambda f: [],
    )
    result = service.diagnose_finding(finding.finding_id, actor="ops-admin-1")
    assert result.report.status.value == "complete"

    # 重新读取：JSONB 完整往返，诊断不动生命周期字段
    reloaded = storage.get_finding(finding.finding_id)
    assert reloaded.diagnosis["status"] == "complete"
    assert reloaded.diagnosis["root_cause"] == "同步连接失败"
    assert reloaded.diagnosis["model_route"]["model_name"] == "fake-diag-model"
    assert reloaded.status is OpsFindingStatus.OPEN
    assert reloaded.revision == finding.revision

    # 二次诊断（无引用）覆盖旧报告为 insufficient_evidence 且无建议动作
    degraded = OpsDiagnosisService(
        storage, lambda: _FixedGateway(_json.dumps({
            "root_cause": "x", "citations": [], "uncertainties": [], "actions": [],
        })),
        evidence_collector=lambda f: [],
    )
    degraded.diagnose_finding(finding.finding_id, actor="ops-admin-1")
    final = storage.get_finding(finding.finding_id)
    assert final.diagnosis["status"] == "insufficient_evidence"
    assert final.diagnosis["actions"] == []


def _reset_schedule_due_now(storage: PostgresOpsFindingStorage) -> None:
    """把调度行复位为立即到期，测试可确定性地抢占 scheduled 巡检。"""
    storage._get_client().execute(
        """UPDATE ops_inspection_schedule
           SET next_run_at = NOW(), active_inspection_id = NULL, updated_at = NOW()
           WHERE schedule_id = 1""",
    )


def test_concurrent_claim_exactly_one_wins_on_live_pg(storage: PostgresOpsFindingStorage):
    """#52 验收：并发巡检不重复执行——双连接同时 claim，恰好一个成功。

    FOR UPDATE SKIP LOCKED：先到者锁调度行写入 running；后到者跳过锁定行
    （或提交后撞 active_inspection_id IS NULL 过滤）空手而归。
    """
    _reset_schedule_due_now(storage)
    # 独立连接的第二存储实例：绕开单客户端操作锁，制造真实并发
    storage_b = PostgresOpsFindingStorage()
    now = datetime.now(timezone.utc)
    barrier = threading.Barrier(2)
    results: list = [None, None]

    def claim(index: int, target: PostgresOpsFindingStorage):
        barrier.wait()
        results[index] = target.claim_inspection(
            now,
            trigger_source=OpsInspectionTrigger.SCHEDULED,
            triggered_by=SMOKE_INSPECTOR,
        )

    threads = [
        threading.Thread(target=claim, args=(0, storage)),
        threading.Thread(target=claim, args=(1, storage_b)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    winners = [run for run in results if run is not None]
    assert len(winners) == 1
    assert winners[0].status is OpsInspectionStatus.RUNNING
    # 调度行被胜者占用；失败方不产生 running 行
    schedule = storage.get_inspection_schedule()
    assert schedule.active_inspection_id == winners[0].inspection_id
    assert storage.get_latest_inspection().inspection_id == winners[0].inspection_id

    # 收尾释放占位并推进 next_run_at（60 分钟后）
    finished = storage.complete_inspection(
        winners[0].inspection_id,
        finished_at=now,
        status=OpsInspectionStatus.SUCCEEDED,
        finding_count=2,
        new_finding_count=1,
        checker_errors=[OpsCheckerError(check_id="data_sync_failed", message="读取失败")],
        next_run_at=now + timedelta(minutes=60),
    )
    assert finished.status is OpsInspectionStatus.SUCCEEDED
    assert finished.checker_errors[0].check_id == "data_sync_failed"
    schedule_after = storage.get_inspection_schedule()
    assert schedule_after.active_inspection_id is None
    assert schedule_after.next_run_at == now + timedelta(minutes=60)

    # 未到期：scheduled 视为 idle；manual 立即到期仍可抢占（force 语义）
    assert storage.claim_inspection(
        now + timedelta(minutes=30),
        trigger_source=OpsInspectionTrigger.SCHEDULED, triggered_by=SMOKE_INSPECTOR,
    ) is None
    manual = storage.claim_inspection(
        now + timedelta(minutes=31),
        trigger_source=OpsInspectionTrigger.MANUAL, triggered_by=SMOKE_INSPECTOR,
    )
    assert manual is not None and manual.trigger_source is OpsInspectionTrigger.MANUAL
    storage.complete_inspection(
        manual.inspection_id,
        finished_at=now + timedelta(minutes=31),
        status=OpsInspectionStatus.FAILED,
        finding_count=0,
        new_finding_count=0,
        checker_errors=[],
        next_run_at=now + timedelta(minutes=91),
    )
    latest = storage.get_latest_inspection()
    assert latest.status is OpsInspectionStatus.FAILED
    assert latest.trigger_source is OpsInspectionTrigger.MANUAL


def test_scheduler_roundtrip_on_live_pg(storage: PostgresOpsFindingStorage):
    """#52：调度器完整闭环在活库成立——claim → 巡检 → 留痕 + 摘要聚合。"""
    from src.runtime.ops.scheduler import OpsInspectionScheduler
    from src.runtime.ops.service import OpsHealthService, OpsInspectionResult

    _reset_schedule_due_now(storage)
    scheduled_at = datetime.now(timezone.utc)

    class _HealthyReader:
        def list_sources(self):
            return []

        def get_job(self, source_id):
            raise LookupError(source_id)

    health = OpsHealthService(storage, lambda: _HealthyReader())
    scheduler = OpsInspectionScheduler(storage, health, interval_minutes=120)

    run = scheduler.run_scheduled_once(now=scheduled_at)
    assert run is not None and run.status is OpsInspectionStatus.SUCCEEDED
    assert run.trigger_source is OpsInspectionTrigger.SCHEDULED
    assert run.finding_count == 0 and run.new_finding_count == 0

    # 完成后 next_run_at 推进 120 分钟；摘要条数据完整
    schedule = storage.get_inspection_schedule()
    assert schedule.next_run_at == scheduled_at + timedelta(minutes=120)
    summary = scheduler.get_summary()
    assert summary.interval_minutes == 120
    assert summary.in_progress is False
    assert summary.latest is not None
    assert summary.latest.inspection_id == run.inspection_id
    assert summary.latest.finished_at == scheduled_at

    # 未到期再跑一轮 → idle；手动触发走同一互斥位
    assert scheduler.run_scheduled_once(now=scheduled_at + timedelta(minutes=10)) is None
    result = scheduler.run_manual(actor="ops-admin-1", now=scheduled_at + timedelta(minutes=11))
    assert result.inspection_id is not None
    assert result.trigger_source is OpsInspectionTrigger.MANUAL
    assert storage.get_latest_inspection().inspection_id == result.inspection_id
    assert OpsInspectionResult.model_validate(result.model_dump()).finding_count == 0
