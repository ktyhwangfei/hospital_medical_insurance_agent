"""L1 自动修复单元测试 — issue #53：白名单闭环（执行 → 强制验证 → resolved/累计）
与 retry_data_sync 执行器（布防 / 内联执行 / 有界等待）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.adapters.insurance_interface.outpatient_source import OutpatientSourceMode
from src.data_platform.outpatient_governance import (
    CdcEnablementStatus,
    ConnectionStatus,
    OutpatientDataSource,
    OutpatientSyncJob,
    SyncJobStatus,
)
from src.data_platform.storage.ops.ops_in_memory import InMemoryOpsFindingStorage
from src.data_platform.storage.postgresql.outpatient_governance_store import (
    OutpatientGovernanceNotFoundError,
)
from src.domain.ops.models import (
    FindingDraft,
    FindingRevisionConflictError,
    InvalidFindingTransitionError,
    OpsAssetType,
    OpsFindingStatus,
    OpsSeverity,
    RemediationNotAllowedError,
    RemediationRiskLevel,
    RemediationRunStatus,
    VerificationResult,
)
from src.runtime.data_governance.service import SyncJobInvalidStateError
from src.runtime.ops.remediation import (
    RemediationActionOutcome,
    RemediationSpec,
    build_data_sync_retry_executor,
)
from src.runtime.ops.service import INSPECTION_ACTOR, OpsHealthService

T0 = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=10)


def _source(source_id: str = "bjybdb") -> OutpatientDataSource:
    return OutpatientDataSource(
        source_id=source_id,
        hospital_code="H001",
        hospital_name="示例医院",
        name="门诊医保库",
        host="db.example",
        database=source_id,
        username="readonly",
        credential_id=f"credential.{source_id}",
        connection_status=ConnectionStatus.HEALTHY,
        cdc_status=CdcEnablementStatus.WAITING_DBA,
        created_at=T0,
        updated_at=T0,
    )


def _job(status: SyncJobStatus, **overrides) -> OutpatientSyncJob:
    defaults = dict(
        source_id="bjybdb",
        source_mode=OutpatientSourceMode.CDC,
        status=status,
        schedule_interval_minutes=5,
        next_run_at=T1,
        last_succeeded_at=T0,
        created_at=T0,
        updated_at=T0,
    )
    defaults.update(overrides)
    return OutpatientSyncJob(**defaults)


class _Reader:
    """验证阶段重跑检查器用的最小读取面。"""

    def __init__(self, sources, jobs):
        self._sources = sources
        self._jobs = jobs

    def list_sources(self):
        if isinstance(self._sources, Exception):
            raise self._sources
        return list(self._sources)

    def get_job(self, source_id):
        if isinstance(self._jobs, Exception):
            raise self._jobs
        if source_id not in self._jobs:
            raise OutpatientGovernanceNotFoundError(f"job {source_id}")
        return self._jobs[source_id]


def _outcome_executed() -> RemediationActionOutcome:
    return RemediationActionOutcome(
        executed=True,
        before_evidence={"job_status": "failed", "last_error_code": "SOURCE_TIMEOUT"},
        after_evidence={"job_status": "running", "last_error_code": None},
    )


def _spec(executor) -> RemediationSpec:
    return RemediationSpec(
        action_id="retry_data_sync",
        check_id="data_sync_failed",
        risk_level=RemediationRiskLevel.L1,
        description="重试门诊同步（测试）",
        executor=executor,
    )


def _service(reader: _Reader, executor, store=None):
    store = store or InMemoryOpsFindingStorage()
    return OpsHealthService(store, lambda: reader, (_spec(executor),)), store


def _seed_sync_finding(store) -> str:
    finding = store.upsert_finding(FindingDraft(
        asset_type=OpsAssetType.DATA,
        asset_id="bjybdb",
        check_id="data_sync_failed",
        severity=OpsSeverity.CRITICAL,
        payload={"problem": "sync_job_failed", "job_status": "failed"},
    ), seen_at=T0)
    return finding.finding_id


class TestRemediationClosedLoop:
    """服务层闭环：验证通过 resolved / 未通过累计保持 open / 未发起只留痕。"""

    def test_pass_path_resolves_finding_with_event_and_run(self):
        # 修复后任务健康（READY + 未滞后）→ 检查器不再产出该问题
        reader = _Reader([_source()], {"bjybdb": _job(SyncJobStatus.READY)})
        service, store = _service(reader, lambda finding, actor: _outcome_executed())
        finding_id = _seed_sync_finding(store)

        result = service.remediate_finding(
            finding_id, expected_revision=1, actor="ops-admin-1",
        )

        assert result.run.status is RemediationRunStatus.SUCCEEDED
        assert result.run.verification_result is VerificationResult.PASSED
        assert result.run.action == "retry_data_sync"
        assert result.run.risk_level is RemediationRiskLevel.L1
        assert result.run.created_by == "ops-admin-1"
        assert result.detail.finding.status is OpsFindingStatus.RESOLVED
        assert [e.event_type.value for e in result.detail.events] == ["resolved"]
        assert "retry_data_sync" in result.detail.events[0].reason
        assert result.detail.remediations == [result.run]

    def test_fail_path_accumulates_occurrence_and_stays_open(self):
        # 修复执行了但任务仍 failed → 验证未通过：保持 open、occurrence+1、证据刷新
        reader = _Reader(
            [_source()],
            {"bjybdb": _job(SyncJobStatus.FAILED, last_error_code="SOURCE_TIMEOUT")},
        )
        service, store = _service(reader, lambda finding, actor: _outcome_executed())
        finding_id = _seed_sync_finding(store)

        result = service.remediate_finding(
            finding_id, expected_revision=1, actor="ops-admin-1",
        )

        assert result.run.verification_result is VerificationResult.FAILED
        finding = result.detail.finding
        assert finding.status is OpsFindingStatus.OPEN
        assert finding.occurrence_count == 2
        assert finding.payload["job_status"] == "failed"  # 复现证据按最新检查刷新

    def test_action_not_executed_records_failed_run_without_verification(self):
        reader = _Reader([_source()], {"bjybdb": _job(SyncJobStatus.READY)})
        outcome = RemediationActionOutcome(
            executed=False,
            after_evidence={"error": "任务处于 paused 状态，不自动重试"},
        )
        service, store = _service(reader, lambda finding, actor: outcome)
        finding_id = _seed_sync_finding(store)

        result = service.remediate_finding(
            finding_id, expected_revision=1, actor="ops-admin-1",
        )

        assert result.run.status is RemediationRunStatus.FAILED
        assert result.run.verification_result is None
        assert result.run.after_evidence["error"].startswith("任务处于 paused")
        assert result.detail.finding.status is OpsFindingStatus.OPEN
        assert result.detail.finding.occurrence_count == 1  # 未验证不累计

    def test_checker_error_leaves_run_unverified(self):
        # 检查器自身故障：不给验证结论，问题状态不动
        reader = _Reader(RuntimeError("控制面不可用"), {})
        service, store = _service(reader, lambda finding, actor: _outcome_executed())
        finding_id = _seed_sync_finding(store)

        result = service.remediate_finding(
            finding_id, expected_revision=1, actor="ops-admin-1",
        )

        assert result.run.verification_result is None
        assert "控制面不可用" in result.run.after_evidence["verification_error"]
        assert result.detail.finding.status is OpsFindingStatus.OPEN

    def test_non_whitelisted_check_rejected(self):
        store = InMemoryOpsFindingStorage()
        finding = store.upsert_finding(FindingDraft(
            asset_type=OpsAssetType.DATA,
            asset_id="bjybdb",
            check_id="data_source_down",
            severity=OpsSeverity.CRITICAL,
            payload={"problem": "connection_error"},
        ), seen_at=T0)
        service, _ = _service(_Reader([], {}), lambda f, a: _outcome_executed(), store=store)

        with pytest.raises(RemediationNotAllowedError):
            service.remediate_finding(finding.finding_id, expected_revision=1, actor="ops-admin-1")
        assert store.list_remediation_runs(finding.finding_id) == []

    def test_non_open_finding_rejected(self):
        reader = _Reader([_source()], {"bjybdb": _job(SyncJobStatus.READY)})
        service, store = _service(reader, lambda f, a: _outcome_executed())
        finding_id = _seed_sync_finding(store)
        service.ignore_finding(
            finding_id, expected_revision=1, reason="排期维护", actor="ops-admin-1",
        )

        with pytest.raises(InvalidFindingTransitionError):
            service.remediate_finding(finding_id, expected_revision=2, actor="ops-admin-1")

    def test_revision_conflict_propagates_but_run_recorded(self):
        reader = _Reader([_source()], {"bjybdb": _job(SyncJobStatus.READY)})
        service, store = _service(reader, lambda f, a: _outcome_executed())
        finding_id = _seed_sync_finding(store)
        store.upsert_finding(FindingDraft(
            asset_type=OpsAssetType.DATA,
            asset_id="bjybdb",
            check_id="data_sync_failed",
            severity=OpsSeverity.CRITICAL,
            payload={"problem": "sync_job_failed"},
        ), seen_at=T1)  # 并发巡检使 revision 1 → 2

        with pytest.raises(FindingRevisionConflictError):
            service.remediate_finding(finding_id, expected_revision=1, actor="ops-admin-1")
        # 动作已执行（幂等可重放），留痕不丢失
        assert len(store.list_remediation_runs(finding_id)) == 1

    def test_list_remediation_actions_reflects_whitelist(self):
        service, _ = _service(_Reader([], {}), lambda f, a: _outcome_executed())
        actions = service.list_remediation_actions()
        assert [(a.action_id, a.check_id, a.risk_level) for a in actions] == [
            ("retry_data_sync", "data_sync_failed", RemediationRiskLevel.L1),
        ]


class TestInspectionReopensResolved:
    """resolved 问题复现由巡检自动复活（ignored 不复活，见 API 侧既有回归）。"""

    def test_resolved_recurrence_reopens_with_system_event(self):
        healthy = _Reader([_source()], {"bjybdb": _job(SyncJobStatus.READY)})
        service, store = _service(healthy, lambda f, a: _outcome_executed())
        finding_id = _seed_sync_finding(store)
        service.remediate_finding(finding_id, expected_revision=1, actor="ops-admin-1")
        assert store.get_finding(finding_id).status is OpsFindingStatus.RESOLVED

        # 修复后又坏：下次巡检产出同一问题 → 自动重开并累计
        broken = OpsHealthService(
            store,
            lambda: _Reader(
                [_source()],
                {"bjybdb": _job(SyncJobStatus.FAILED, last_error_code="SOURCE_TIMEOUT")},
            ),
            (_spec(lambda f, a: _outcome_executed()),),
        )
        inspection = broken.run_inspection(now=T1)
        assert inspection.finding_count == 1
        finding = store.get_finding(finding_id)
        assert finding.status is OpsFindingStatus.OPEN
        assert finding.occurrence_count == 2  # 首见 + 复现
        events = store.list_finding_events(finding_id)
        assert [e.event_type.value for e in events] == ["resolved", "reopened"]
        assert events[-1].actor == INSPECTION_ACTOR

    def test_healthy_recurrence_after_resolved_does_not_reopen(self):
        healthy = _Reader([_source()], {"bjybdb": _job(SyncJobStatus.READY)})
        service, store = _service(healthy, lambda f, a: _outcome_executed())
        finding_id = _seed_sync_finding(store)
        service.remediate_finding(finding_id, expected_revision=1, actor="ops-admin-1")

        # 读取面保持健康：巡检不再产出该问题，resolved 保持
        inspection = service.run_inspection(now=T1)
        assert inspection.finding_count == 0
        assert store.get_finding(finding_id).status is OpsFindingStatus.RESOLVED


class _FakeGovernanceService:
    """执行器测试用治理控制面：记录布防调用并模拟状态迁移。"""

    def __init__(self, job: OutpatientSyncJob | None, *, error_on_arm: Exception | None = None):
        self.job = job
        self.error_on_arm = error_on_arm
        self.calls: list[str] = []

    def get_job(self, source_id):
        if self.job is None:
            raise OutpatientGovernanceNotFoundError(source_id)
        return self.job

    def request_run_once(self, source_id, actor):
        self.calls.append("request_run_once")
        if self.error_on_arm:
            raise self.error_on_arm
        now = datetime.now(timezone.utc)
        self.job = self.job.model_copy(update={
            "run_once_requested_at": now, "updated_at": now,
        })
        return self.job

    def start_job(self, source_id, actor):
        self.calls.append("start_job")
        if self.error_on_arm:
            raise self.error_on_arm
        now = datetime.now(timezone.utc)
        self.job = self.job.model_copy(update={
            "status": SyncJobStatus.READY,
            "next_run_at": now,
            "updated_at": now,
        })
        return self.job


class _FakeWorker:
    def __init__(self, result, on_run=None):
        self._result = result
        self._on_run = on_run
        self.ran = False

    def run_one(self, *, now=None):
        self.ran = True
        if self._on_run:
            self._on_run()
        return self._result


def _inline_result(source_id="bjybdb"):
    return SimpleNamespace(status="success", source_id=source_id, attempt_id="a1", batch_id="b1")


def _executor(service, worker, **kwargs):
    return build_data_sync_retry_executor(
        lambda: service, lambda: worker,
        settle_timeout_seconds=kwargs.pop("settle_timeout_seconds", 2.0),
        settle_poll_seconds=kwargs.pop("settle_poll_seconds", 0.01),
    )


def _finding() -> SimpleNamespace:
    return SimpleNamespace(asset_type=OpsAssetType.DATA, asset_id="bjybdb",
                           check_id="data_sync_failed")


class TestRetryDataSyncExecutor:
    """retry_data_sync：按任务状态布防 → 内联执行 → 前后证据快照。"""

    def test_failed_job_arms_via_start_job_and_executes_inline(self):
        service = _FakeGovernanceService(
            _job(SyncJobStatus.FAILED, last_error_code="SOURCE_TIMEOUT")
        )

        def simulate_sync():
            now = datetime.now(timezone.utc)
            service.job = service.job.model_copy(update={
                "status": SyncJobStatus.RUNNING, "last_error_code": None,
                "last_succeeded_at": now, "last_started_at": now, "updated_at": now,
            })

        worker = _FakeWorker(_inline_result(), on_run=simulate_sync)
        outcome = _executor(service, worker)(_finding(), "ops-admin-1")

        assert outcome.executed is True
        assert service.calls == ["start_job"]
        assert worker.ran is True
        assert outcome.before_evidence["job_status"] == "failed"
        assert outcome.before_evidence["last_error_code"] == "SOURCE_TIMEOUT"
        assert outcome.after_evidence["job_status"] == "running"
        assert outcome.after_evidence["last_error_code"] is None

    def test_lagging_ready_job_requests_run_once(self):
        service = _FakeGovernanceService(
            _job(SyncJobStatus.READY, next_run_at=T0 - timedelta(hours=1))
        )
        worker = _FakeWorker(_inline_result())
        outcome = _executor(service, worker)(_finding(), "ops-admin-1")

        assert outcome.executed is True
        assert service.calls == ["request_run_once"]

    def test_paused_job_not_executed(self):
        service = _FakeGovernanceService(_job(SyncJobStatus.PAUSED))
        worker = _FakeWorker(_inline_result())
        outcome = _executor(service, worker)(_finding(), "ops-admin-1")

        assert outcome.executed is False
        assert worker.ran is False
        assert "不自动重试" in outcome.after_evidence["error"]
        assert outcome.before_evidence["job_status"] == "paused"

    def test_arm_precondition_failure_recorded(self):
        service = _FakeGovernanceService(
            _job(SyncJobStatus.FAILED),
            error_on_arm=SyncJobInvalidStateError("门诊源表尚未通过可读检测"),
        )
        worker = _FakeWorker(_inline_result())
        outcome = _executor(service, worker)(_finding(), "ops-admin-1")

        assert outcome.executed is False
        assert worker.ran is False
        assert outcome.after_evidence["error"] == "门诊源表尚未通过可读检测"

    def test_worker_claimed_other_source_waits_for_settle(self):
        # 内联认领到其他到期任务：有界等待目标任务本次尝试收敛后再取快照
        service = _FakeGovernanceService(_job(SyncJobStatus.FAILED))
        worker = _FakeWorker(_inline_result(source_id="other-source"))
        outcome = _executor(
            service, worker, settle_timeout_seconds=0.2,
        )(_finding(), "ops-admin-1")

        assert outcome.executed is True
        # start_job 的模型拷贝未更新 last_started_at → 未观察到本次尝试完成，
        # 等待超时后按当前快照收尾（不留脏状态、不误报验证）
        assert outcome.after_evidence["job_status"] == "ready"

    def test_job_not_found_not_executed(self):
        service = _FakeGovernanceService(None)
        worker = _FakeWorker(_inline_result())
        outcome = _executor(service, worker)(_finding(), "ops-admin-1")

        assert outcome.executed is False
        assert worker.ran is False
        assert "不存在" in outcome.after_evidence["error"]
