"""L2 人工确认修复流单元测试 — issue #54：转人工（task_closure 复用）+
完成自动复检（复用 #53 验证闭环三分支）+ 状态机守卫负例。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

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
    ManualTaskNotFoundError,
    OpsAssetType,
    OpsFindingEventType,
    OpsFindingStatus,
    OpsManualTarget,
    OpsSeverity,
    manual_target_for_asset,
)
from src.runtime.ops.service import MANUAL_RESPONSIBLE_ROLE, MANUAL_TASK_TYPE, OpsHealthService
from src.runtime.task_closure import service as task_service

T0 = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


class _FakeTaskStore:
    """task_closure 内存替身——create_task 的 workflow_id 是第 5 个位置参数。"""

    def __init__(self):
        self._tasks: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []

    def create_task(
        self,
        task_id: str,
        task_type: str,
        description: str,
        responsible_role: str,
        workflow_id: str | None = None,
        executor_type: str | None = None,
        input_data: dict | None = None,
        output_data: dict | None = None,
        step_id: str | None = None,
        error_message: str | None = None,
        duration_ms: float | None = None,
        status: str = "pending",
    ) -> dict[str, Any]:
        task: dict[str, Any] = {
            "task_id": task_id,
            "task_type": task_type,
            "status": status,
            "description": description,
            "responsible_role": responsible_role,
            "workflow_id": workflow_id,
            "updated_at": "2026-09-11T04:00:00+00:00",
        }
        if input_data is not None:
            task["input_data"] = input_data
        if output_data is not None:
            task["output_data"] = output_data
        return self.save_task(task)

    def save_task(self, task: dict[str, Any]) -> dict[str, Any]:
        if task["task_id"] not in self._tasks:
            self._order.append(task["task_id"])
        self._tasks[task["task_id"]] = task
        return task

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self._tasks.get(task_id)

    def list_tasks_by_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
        return [
            self._tasks[task_id] for task_id in self._order
            if self._tasks[task_id].get("workflow_id") == workflow_id
        ]


@pytest.fixture(autouse=True)
def memory_task_store(monkeypatch):
    """隔离任务存储：不触真实 PG，也不受 USE_MEMORY_STORAGE 影响。"""
    store = _FakeTaskStore()
    monkeypatch.setattr(task_service, "_task_store", store)
    return store


def _source(status: ConnectionStatus = ConnectionStatus.HEALTHY) -> OutpatientDataSource:
    # 注意：首参是连接状态而非 source_id（StrEnum 值会误当 source_id 用）
    return OutpatientDataSource(
        source_id="bjybdb",
        hospital_code="H001",
        hospital_name="示例医院",
        name="门诊医保库",
        host="db.example",
        database="bjybdb",
        username="readonly",
        credential_id="credential.bjybdb",
        connection_status=status,
        cdc_status=CdcEnablementStatus.WAITING_DBA,
        created_at=T0,
        updated_at=T0,
    )


def _job(status: SyncJobStatus) -> OutpatientSyncJob:
    # next_run_at 相对真实时钟取未来值：验证环节用 datetime.now 判滞后
    return OutpatientSyncJob(
        source_id="bjybdb",
        source_mode=OutpatientSourceMode.CDC,
        status=status,
        schedule_interval_minutes=5,
        next_run_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        last_succeeded_at=T0,
        created_at=T0,
        updated_at=T0,
    )


class _Reader:
    def __init__(self, sources=None, jobs=None):
        self._sources = sources if sources is not None else []
        self._jobs = jobs if jobs is not None else {}

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


def _service(reader: _Reader) -> tuple[OpsHealthService, InMemoryOpsFindingStorage]:
    store = InMemoryOpsFindingStorage()
    return OpsHealthService(store, lambda: reader), store


def _seed(store, *, asset_type: OpsAssetType = OpsAssetType.DATA,
          asset_id: str = "bjybdb", check_id: str = "data_sync_failed") -> str:
    finding = store.upsert_finding(FindingDraft(
        asset_type=asset_type,
        asset_id=asset_id,
        check_id=check_id,
        severity=OpsSeverity.WARNING,
        payload={"problem": "sync_job_degraded"},
    ), seen_at=T0)
    return finding.finding_id


class TestManualTargetMapping:
    def test_asset_type_maps_to_manual_target(self):
        assert manual_target_for_asset(OpsAssetType.KNOWLEDGE) is OpsManualTarget.POLICY_KNOWLEDGE
        assert manual_target_for_asset(OpsAssetType.SKILL) is OpsManualTarget.SKILL_DRAFT
        assert manual_target_for_asset(OpsAssetType.DATA) is OpsManualTarget.EXTERNAL
        assert manual_target_for_asset(OpsAssetType.RUNTIME) is OpsManualTarget.EXTERNAL


class TestRequestManual:
    def test_open_to_waiting_human_creates_task_and_event(self, memory_task_store):
        service, store = _service(_Reader([_source()], {"bjybdb": _job(SyncJobStatus.DEGRADED)}))
        finding_id = _seed(store)

        result = service.request_manual_handling(
            finding_id, expected_revision=1, actor="ops-admin-1", note="需人工核对",
        )

        assert result.detail.finding.status is OpsFindingStatus.WAITING_HUMAN
        assert result.detail.finding.revision == 2
        manual = result.manual_task
        assert manual.task_id.startswith("opsmanual_")
        assert manual.status == "waiting_human_confirmation"
        assert manual.target is OpsManualTarget.EXTERNAL  # 数据资产 → 外部
        assert manual.requested_by == "ops-admin-1"
        assert manual.note == "需人工核对"
        assert manual.requested_at.tzinfo is not None
        # 任务真实落在 task_closure 存储，可按 workflow_id 反查
        tasks = memory_task_store.list_tasks_by_workflow(finding_id)
        assert len(tasks) == 1
        assert tasks[0]["task_type"] == MANUAL_TASK_TYPE
        assert tasks[0]["responsible_role"] == MANUAL_RESPONSIBLE_ROLE
        assert tasks[0]["input_data"]["target"] == "external"
        # 详情投影 + 事件留痕
        assert result.detail.manual_task.task_id == manual.task_id
        assert [e.event_type for e in result.detail.events] == [
            OpsFindingEventType.MANUAL_REQUESTED,
        ]

    def test_target_follows_asset_type(self, memory_task_store):
        service, store = _service(_Reader([_source()], {}))
        knowledge_id = _seed(store, asset_type=OpsAssetType.KNOWLEDGE, asset_id="rule-42",
                             check_id="knowledge_stale")

        result = service.request_manual_handling(knowledge_id, expected_revision=1,
                                                 actor="ops-admin-1")
        assert result.manual_task.target is OpsManualTarget.POLICY_KNOWLEDGE

        skill_id = _seed(store, asset_type=OpsAssetType.SKILL, asset_id="settlement_explain",
                         check_id="skill_schema_drift")
        result = service.request_manual_handling(skill_id, expected_revision=1,
                                                 actor="ops-admin-1")
        assert result.manual_task.target is OpsManualTarget.SKILL_DRAFT

    def test_non_open_finding_rejected(self, memory_task_store):
        service, store = _service(_Reader([_source()], {}))
        finding_id = _seed(store)
        service.ignore_finding(finding_id, expected_revision=1, reason="排期",
                               actor="ops-admin-1")

        with pytest.raises(InvalidFindingTransitionError):
            service.request_manual_handling(finding_id, expected_revision=2,
                                            actor="ops-admin-1")
        assert memory_task_store.list_tasks_by_workflow(finding_id) == []

    def test_revision_conflict_raises_without_dangling_task(self, memory_task_store):
        service, store = _service(_Reader([_source()], {"bjybdb": _job(SyncJobStatus.DEGRADED)}))
        finding_id = _seed(store)
        # 并发巡检复现使 revision 1 → 2
        store.upsert_finding(FindingDraft(
            asset_type=OpsAssetType.DATA, asset_id="bjybdb", check_id="data_sync_failed",
            severity=OpsSeverity.WARNING, payload={"problem": "sync_job_degraded"},
        ), seen_at=T0)

        with pytest.raises(FindingRevisionConflictError):
            service.request_manual_handling(finding_id, expected_revision=1,
                                            actor="ops-admin-1")
        # 先验版本再写任务：冲突时不留悬空确认任务
        assert memory_task_store._tasks == {}
        assert store.get_finding(finding_id).status is OpsFindingStatus.OPEN


class TestCompleteManual:
    def test_verification_pass_resolves_with_backfill(self, memory_task_store):
        reader = _Reader([_source()], {"bjybdb": _job(SyncJobStatus.DEGRADED)})
        service, store = _service(reader)
        finding_id = _seed(store)
        requested = service.request_manual_handling(finding_id, expected_revision=1,
                                                    actor="ops-admin-1")
        task_id = requested.manual_task.task_id
        reader._jobs["bjybdb"] = _job(SyncJobStatus.READY)  # 治理页修复后任务健康

        result = service.complete_manual_handling(
            finding_id, expected_revision=2, actor="ops-admin-2", result_note="已修正凭据",
        )

        assert result.detail.finding.status is OpsFindingStatus.RESOLVED
        manual = result.manual_task
        assert manual.task_id == task_id
        assert manual.status == "completed"
        assert manual.handled_by == "ops-admin-2"
        assert manual.result_note == "已修正凭据"
        assert manual.handled_at is not None
        events = result.detail.events
        assert [e.event_type for e in events] == [
            OpsFindingEventType.MANUAL_REQUESTED, OpsFindingEventType.RESOLVED,
        ]
        assert "复检通过" in events[-1].reason
        # 任务存储侧同步完成
        assert memory_task_store.get_task(task_id)["status"] == "completed"

    def test_verification_fail_reopens_with_recurrence(self, memory_task_store):
        # 任务仍 DEGRADED → 复检仍报：回 open 且按最新草稿累计复现
        service, store = _service(_Reader([_source()], {"bjybdb": _job(SyncJobStatus.DEGRADED)}))
        finding_id = _seed(store)
        service.request_manual_handling(finding_id, expected_revision=1, actor="ops-admin-1")

        result = service.complete_manual_handling(
            finding_id, expected_revision=2, actor="ops-admin-2", result_note="修了但没修好",
        )

        finding = result.detail.finding
        assert finding.status is OpsFindingStatus.OPEN
        assert finding.occurrence_count == 2
        assert result.manual_task.status == "completed"
        events = result.detail.events
        assert [e.event_type for e in events] == [
            OpsFindingEventType.MANUAL_REQUESTED, OpsFindingEventType.MANUAL_COMPLETED,
        ]
        assert "复检仍报" in events[-1].reason

    def test_checker_error_reopens_without_verification_verdict(self, memory_task_store):
        service, store = _service(_Reader(RuntimeError("控制面不可用"), {}))
        finding_id = _seed(store)
        service.request_manual_handling(finding_id, expected_revision=1, actor="ops-admin-1")

        result = service.complete_manual_handling(
            finding_id, expected_revision=2, actor="ops-admin-2", result_note="已处理",
        )

        # 检查器异常不判定验证：回 open 待下次巡检，任务仍完成登记
        assert result.detail.finding.status is OpsFindingStatus.OPEN
        assert result.detail.finding.occurrence_count == 1  # 未验证不累计
        assert result.manual_task.status == "completed"
        assert "复检异常" in result.detail.events[-1].reason

    def test_missing_task_raises(self, memory_task_store):
        service, store = _service(_Reader([_source()], {}))
        finding_id = _seed(store)

        with pytest.raises(ManualTaskNotFoundError):
            service.complete_manual_handling(
                finding_id, expected_revision=1, actor="ops-admin-1", result_note="x",
            )

    def test_double_complete_is_idempotent(self, memory_task_store):
        reader = _Reader([_source()], {"bjybdb": _job(SyncJobStatus.DEGRADED)})
        service, store = _service(reader)
        finding_id = _seed(store)
        service.request_manual_handling(finding_id, expected_revision=1, actor="ops-admin-1")
        reader._jobs["bjybdb"] = _job(SyncJobStatus.READY)
        first = service.complete_manual_handling(
            finding_id, expected_revision=2, actor="ops-admin-2", result_note="已修正",
        )
        assert first.detail.finding.status is OpsFindingStatus.RESOLVED

        second = service.complete_manual_handling(
            finding_id, expected_revision=first.detail.finding.revision,
            actor="ops-admin-2", result_note="重复登记",
        )
        # 幂等回读：状态不变、事件不新增、结果不被覆盖
        assert second.detail.finding.status is OpsFindingStatus.RESOLVED
        assert len(second.detail.events) == 2
        assert second.manual_task.result_note == "已修正"

    def test_complete_on_open_finding_without_task_raises(self, memory_task_store):
        # 撤回人工处理后（任务已完成、问题 open）直接 complete：诚实 404 语义
        service, store = _service(_Reader([_source()], {}))
        finding_id = _seed(store)

        with pytest.raises(ManualTaskNotFoundError):
            service.complete_manual_handling(
                finding_id, expected_revision=1, actor="ops-admin-1", result_note="x",
            )


class TestWaitingHumanGuards:
    """验收负例：未完成人工确认前，问题不得经 remediate/ignore 离开 waiting_human。"""

    def _to_waiting(self, store, reader):
        service = OpsHealthService(store, lambda: reader)
        finding_id = _seed(store)
        service.request_manual_handling(finding_id, expected_revision=1, actor="ops-admin-1")
        return service, finding_id

    def test_remediate_and_ignore_blocked(self, memory_task_store):
        reader = _Reader([_source()], {"bjybdb": _job(SyncJobStatus.DEGRADED)})
        store = InMemoryOpsFindingStorage()
        service, finding_id = self._to_waiting(store, reader)

        with pytest.raises(InvalidFindingTransitionError):
            service.remediate_finding(finding_id, expected_revision=2, actor="ops-admin-1")
        with pytest.raises(InvalidFindingTransitionError):
            service.ignore_finding(finding_id, expected_revision=2, reason="想忽略",
                                   actor="ops-admin-1")
        assert store.get_finding(finding_id).status is OpsFindingStatus.WAITING_HUMAN

    def test_reopen_withdraws_manual_handling(self, memory_task_store):
        reader = _Reader([_source()], {"bjybdb": _job(SyncJobStatus.DEGRADED)})
        store = InMemoryOpsFindingStorage()
        service, finding_id = self._to_waiting(store, reader)

        detail = service.reopen_finding(finding_id, expected_revision=2, actor="ops-admin-1")

        assert detail.finding.status is OpsFindingStatus.OPEN
        # 任务留痕不删，可再次转人工创建新任务
        assert len(memory_task_store.list_tasks_by_workflow(finding_id)) == 1
        again = service.request_manual_handling(finding_id, expected_revision=3,
                                                actor="ops-admin-1")
        assert again.manual_task.task_id != memory_task_store.list_tasks_by_workflow(
            finding_id)[0]["task_id"]

    def test_task_type_constants(self):
        assert MANUAL_TASK_TYPE == "ops_manual_remediation"
        assert MANUAL_RESPONSIBLE_ROLE == "ops_admin"
