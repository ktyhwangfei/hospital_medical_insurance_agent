"""定时巡检调度单元测试 — issue #52 P1-6。

OpsInspectionScheduler：claim 抢占 → 复用巡检 → 完成回填留痕、
手动/定时互斥（执行中手动触发抛 InspectionInProgressError）、
未到期定时视为 idle、周期环境变量覆盖、巡检整体异常落 failed 留痕。
并发不重复执行的 PG 真语义（FOR UPDATE SKIP LOCKED）在活库冒烟验证。
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from src.data_platform.storage.ops.ops_in_memory import InMemoryOpsFindingStorage
from src.domain.ops.models import (
    InspectionInProgressError,
    OpsAssetType,
    OpsCheckerError,
    OpsFinding,
    OpsFindingStatus,
    OpsInspectionStatus,
    OpsInspectionTrigger,
    OpsSeverity,
)
from src.runtime.ops.scheduler import (
    SCHEDULER_ACTOR,
    OpsInspectionScheduler,
    default_inspection_interval_minutes,
)
from src.runtime.ops.service import OpsInspectionResult

T0 = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)


def _finding(finding_id: str, occurrence_count: int) -> OpsFinding:
    return OpsFinding(
        finding_id=finding_id,
        asset_type=OpsAssetType.DATA,
        asset_id="src-1",
        check_id="data_sync_failed",
        severity=OpsSeverity.WARNING,
        status=OpsFindingStatus.OPEN,
        fingerprint=f"data:src-1:data_sync_failed#{finding_id}",
        payload={},
        first_seen_at=T0,
        last_seen_at=T0,
        occurrence_count=occurrence_count,
        revision=occurrence_count,
    )


class _StubHealth:
    """受控巡检服务：返回固定结果或抛错，不触真实检查器。"""

    def __init__(self, result: OpsInspectionResult | None = None, error: Exception | None = None):
        self._result = result or OpsInspectionResult(
            checked_at=T0, check_count=2, finding_count=0, findings=[], checker_errors=[],
        )
        self._error = error
        self.calls: list[datetime] = []

    def run_inspection(self, *, now=None):
        self.calls.append(now)
        if self._error is not None:
            raise self._error
        return self._result.model_copy(update={"checked_at": now or T0})


def _scheduler(storage, health, *, interval_minutes=None) -> OpsInspectionScheduler:
    return OpsInspectionScheduler(storage, health, interval_minutes=interval_minutes)


class TestIntervalConfig:
    def test_default_daily(self):
        assert default_inspection_interval_minutes() == 1440

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OPS_INSPECTION_INTERVAL_MINUTES", "30")
        assert default_inspection_interval_minutes() == 30

    @pytest.mark.parametrize("bad", ["abc", "0", "-5", "  "])
    def test_invalid_env_falls_back_to_default(self, monkeypatch, bad):
        monkeypatch.setenv("OPS_INSPECTION_INTERVAL_MINUTES", bad)
        assert default_inspection_interval_minutes() == 1440

    def test_explicit_interval_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("OPS_INSPECTION_INTERVAL_MINUTES", "30")
        scheduler = _scheduler(InMemoryOpsFindingStorage(), _StubHealth(), interval_minutes=60)
        assert scheduler.interval_minutes == 60


class TestManualInspection:
    def test_writes_run_record_and_enriches_result(self):
        storage = InMemoryOpsFindingStorage()
        health = _StubHealth(OpsInspectionResult(
            checked_at=T0, check_count=2, finding_count=2,
            findings=[_finding("f1", 1), _finding("f2", 2)], checker_errors=[],
        ))
        scheduler = _scheduler(storage, health)

        result = scheduler.run_manual(actor="ops-admin-1", now=T0)

        # 结果回填运行留痕字段；new_finding_count 只计首见
        assert result.inspection_id is not None
        assert result.trigger_source is OpsInspectionTrigger.MANUAL
        assert result.new_finding_count == 1

        run = storage.get_inspection(result.inspection_id)
        assert run.status is OpsInspectionStatus.SUCCEEDED
        assert run.trigger_source is OpsInspectionTrigger.MANUAL
        assert run.triggered_by == "ops-admin-1"
        assert run.started_at == T0 and run.finished_at == T0
        assert run.finding_count == 2 and run.new_finding_count == 1
        assert run.checker_errors == []
        # 调度行释放占位，next_run_at 推进一个周期（默认每日）
        schedule = storage.get_inspection_schedule()
        assert schedule.active_inspection_id is None
        assert schedule.next_run_at == T0 + timedelta(minutes=1440)

    def test_in_progress_rejected(self):
        storage = InMemoryOpsFindingStorage()
        # 直接抢占一个 running 占位，模拟巡检执行中
        claimed = storage.claim_inspection(
            T0, trigger_source=OpsInspectionTrigger.SCHEDULED, triggered_by=SCHEDULER_ACTOR,
        )
        assert claimed is not None
        scheduler = _scheduler(storage, _StubHealth())

        with pytest.raises(InspectionInProgressError) as excinfo:
            scheduler.run_manual(actor="ops-admin-1", now=T0)
        assert excinfo.value.active_inspection_id == claimed.inspection_id

    def test_checker_errors_recorded_in_run(self):
        storage = InMemoryOpsFindingStorage()
        health = _StubHealth(OpsInspectionResult(
            checked_at=T0, check_count=2, finding_count=0, findings=[],
            checker_errors=[OpsCheckerError(check_id="data_sync_failed", message="读取失败")],
        ))
        result = _scheduler(storage, health).run_manual(actor="ops-admin-1", now=T0)
        run = storage.get_inspection(result.inspection_id)
        assert [err.check_id for err in run.checker_errors] == ["data_sync_failed"]
        assert run.status is OpsInspectionStatus.SUCCEEDED  # 检查器失败≠巡检失败

    def test_catastrophic_failure_records_failed_and_raises(self):
        storage = InMemoryOpsFindingStorage()
        scheduler = _scheduler(storage, _StubHealth(error=RuntimeError("存储连接失败")))

        with pytest.raises(RuntimeError):
            scheduler.run_manual(actor="ops-admin-1", now=T0)

        latest = storage.get_latest_inspection()
        assert latest.status is OpsInspectionStatus.FAILED
        assert latest.finished_at == T0
        # 安全文案落库，异常原文不进运行记录
        assert latest.checker_errors == [
            OpsCheckerError(check_id="inspection", message="巡检执行异常，详见服务端日志"),
        ]
        # 失败也释放占位并推迟下轮一个周期（避免失败风暴）
        schedule = storage.get_inspection_schedule()
        assert schedule.active_inspection_id is None
        assert schedule.next_run_at == T0 + timedelta(minutes=1440)


class TestScheduledInspection:
    def test_not_due_returns_none(self):
        storage = InMemoryOpsFindingStorage()
        # 先跑一次手动巡检，把 next_run_at 推到 T0+1440m
        _scheduler(storage, _StubHealth()).run_manual(actor="ops-admin-1", now=T0)
        scheduler = _scheduler(storage, _StubHealth())

        assert scheduler.run_scheduled_once(now=T0 + timedelta(minutes=10)) is None
        assert storage.get_latest_inspection().trigger_source is OpsInspectionTrigger.MANUAL

    def test_due_runs_and_records_scheduled_trigger(self):
        storage = InMemoryOpsFindingStorage()
        _scheduler(storage, _StubHealth()).run_manual(actor="ops-admin-1", now=T0)
        scheduler = _scheduler(storage, _StubHealth())

        due = T0 + timedelta(minutes=1440, seconds=1)
        run = scheduler.run_scheduled_once(now=due)

        assert run is not None
        assert run.trigger_source is OpsInspectionTrigger.SCHEDULED
        assert run.triggered_by == SCHEDULER_ACTOR
        assert run.status is OpsInspectionStatus.SUCCEEDED
        assert storage.get_inspection_schedule().next_run_at == due + timedelta(minutes=1440)

    def test_scheduled_failure_returns_failed_run_without_raising(self):
        storage = InMemoryOpsFindingStorage()
        scheduler = _scheduler(storage, _StubHealth(error=RuntimeError("boom")))

        run = scheduler.run_scheduled_once(now=T0)  # 新库 epoch 立即到期

        assert run is not None and run.status is OpsInspectionStatus.FAILED
        assert storage.get_inspection_schedule().active_inspection_id is None


class TestSummary:
    def test_summary_reflects_latest_and_interval(self, monkeypatch):
        monkeypatch.setenv("OPS_INSPECTION_INTERVAL_MINUTES", "120")
        storage = InMemoryOpsFindingStorage()
        scheduler = _scheduler(storage, _StubHealth())

        empty = scheduler.get_summary()
        assert empty.latest is None and empty.in_progress is False
        assert empty.interval_minutes == 120

        scheduler.run_manual(actor="ops-admin-1", now=T0)
        summary = scheduler.get_summary()
        assert summary.latest is not None
        assert summary.latest.status is OpsInspectionStatus.SUCCEEDED
        assert summary.in_progress is False
        assert summary.next_run_at == T0 + timedelta(minutes=120)

    def test_summary_in_progress_true_while_running(self):
        storage = InMemoryOpsFindingStorage()
        storage.claim_inspection(
            T0, trigger_source=OpsInspectionTrigger.SCHEDULED, triggered_by=SCHEDULER_ACTOR,
        )
        summary = _scheduler(storage, _StubHealth()).get_summary()
        assert summary.in_progress is True
        assert summary.latest is not None
        assert summary.latest.status is OpsInspectionStatus.RUNNING


class TestConcurrentClaim:
    def test_parallel_claims_exactly_one_wins(self):
        """验收：并发巡检不重复执行——8 线程同时抢占，恰好 1 个成功。

        PG 侧同一语义由 FOR UPDATE SKIP LOCKED + active 互斥保证，
        活库冒烟（test_ops_pg_smoke）用双连接复验。
        """
        storage = InMemoryOpsFindingStorage()
        barrier = threading.Barrier(8)
        results: list = [None] * 8

        def claim(index: int):
            barrier.wait()
            results[index] = storage.claim_inspection(
                T0, trigger_source=OpsInspectionTrigger.SCHEDULED,
                triggered_by=SCHEDULER_ACTOR,
            )

        threads = [threading.Thread(target=claim, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        winners = [run for run in results if run is not None]
        assert len(winners) == 1
        assert storage.get_inspection_schedule().active_inspection_id == winners[0].inspection_id
