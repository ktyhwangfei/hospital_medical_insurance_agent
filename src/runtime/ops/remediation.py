"""健康运营 L1 自动修复 — 白名单注册与门诊同步重试动作（issue #53）。

白名单只收「幂等、可重放、可验证」的动作（调研方案 §6.5-3）：本期仅
retry_data_sync（重试失败/滞后的门诊同步任务，复用 data_governance 同步
入口）；重跑回归评测 / 重建 Milvus 索引随其触发检查器
（skill_regression_failure / knowledge_index_mismatch）落地后注册。
非白名单检查项（如 data_source_down 连接失败）只允许人工处置。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from typing import Any, Callable, Protocol

from pydantic import BaseModel, Field

from src.data_platform.outpatient_governance import OutpatientSyncJob, SyncJobStatus
from src.data_platform.storage.postgresql.outpatient_governance_store import (
    OutpatientGovernanceConflictError,
    OutpatientGovernanceNotFoundError,
)
from src.domain.ops.models import OpsFinding, RemediationRiskLevel
from src.runtime.data_governance.service import SyncJobInvalidStateError


class RemediationActionOutcome(BaseModel):
    """L1 动作单次执行结果（服务层据此落 OpsRemediationRun）。

    executed=False 表示动作未能发起（如任务已暂停、前置条件不满足），
    after_evidence.error 携带安全原因；此时不做修复后验证。
    """

    executed: bool
    before_evidence: dict[str, Any] = Field(default_factory=dict)
    after_evidence: dict[str, Any] = Field(default_factory=dict)


RemediationExecutor = Callable[[OpsFinding, str], RemediationActionOutcome]


@dataclass(frozen=True)
class RemediationSpec:
    """修复白名单注册项：某检查项允许自动执行的 L1 动作。"""

    action_id: str
    check_id: str
    risk_level: RemediationRiskLevel
    description: str
    executor: RemediationExecutor


class _GovernanceService(Protocol):
    """重试动作对治理控制面的最小依赖（DataGovernanceService 已满足）。"""

    def get_job(self, source_id: str) -> OutpatientSyncJob: ...

    def request_run_once(self, source_id: str, actor: str) -> OutpatientSyncJob: ...

    def start_job(self, source_id: str, actor: str) -> OutpatientSyncJob: ...


class _SyncWorker(Protocol):
    """与后台 sync worker 同构的同步执行入口。"""

    def run_one(self, *, now: datetime | None = None): ...


def _job_evidence(job: OutpatientSyncJob) -> dict[str, Any]:
    """任务状态安全快照（状态码/时间戳，不含凭据与连接串）。"""
    return {
        "job_status": job.status.value,
        "last_error_code": job.last_error_code,
        "last_started_at": job.last_started_at.isoformat()
        if job.last_started_at else None,
        "last_succeeded_at": job.last_succeeded_at.isoformat()
        if job.last_succeeded_at else None,
    }


def build_data_sync_retry_executor(
    service_factory: Callable[[], _GovernanceService],
    worker_factory: Callable[[], _SyncWorker],
    *,
    settle_timeout_seconds: float = 60.0,
    settle_poll_seconds: float = 1.0,
) -> RemediationExecutor:
    """构造 retry_data_sync 动作：布防 → 内联同步执行 → 前后证据快照。

    failed/degraded 任务走 start_job 重新启用（立即到期），滞后任务走
    request_run_once；随后与后台 worker 同路径内联执行一次（认领原子，
    FOR UPDATE SKIP LOCKED）。被后台 worker 抢先或认领到其他到期任务时，
    有界等待目标任务的本次尝试收敛后再取快照。
    """

    def execute(finding: OpsFinding, actor: str) -> RemediationActionOutcome:
        service = service_factory()
        source_id = finding.asset_id
        try:
            job = service.get_job(source_id)
        except OutpatientGovernanceNotFoundError:
            return RemediationActionOutcome(
                executed=False,
                after_evidence={"error": "同步任务不存在（数据源可能已删除）"},
            )
        before = _job_evidence(job)
        if job.status in (SyncJobStatus.PAUSED, SyncJobStatus.DRAFT):
            # 暂停是运维者的显式决策，自动修复不得越过；草稿任务同理
            return RemediationActionOutcome(
                executed=False,
                before_evidence=before,
                after_evidence={**before, "error": f"任务处于 {job.status.value} 状态，不自动重试"},
            )
        armed_at = datetime.now(timezone.utc)
        try:
            if job.status in (SyncJobStatus.READY, SyncJobStatus.RUNNING):
                service.request_run_once(source_id, actor)
            else:
                service.start_job(source_id, actor)
        except (SyncJobInvalidStateError, OutpatientGovernanceConflictError) as exc:
            return RemediationActionOutcome(
                executed=False,
                before_evidence=before,
                after_evidence={**before, "error": str(exc)},
            )
        result = worker_factory().run_one()
        if getattr(result, "source_id", None) != source_id:
            _wait_attempt_settled(
                service, source_id, armed_at, settle_timeout_seconds, settle_poll_seconds,
            )
        after = _job_evidence(service.get_job(source_id))
        return RemediationActionOutcome(
            executed=True, before_evidence=before, after_evidence=after,
        )

    return execute


def _wait_attempt_settled(
    service: _GovernanceService,
    source_id: str,
    armed_at: datetime,
    timeout_seconds: float,
    poll_seconds: float,
) -> None:
    """有界等待布防后的那次尝试结束（last_started_at 更新且无活跃尝试）。"""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            job = service.get_job(source_id)
        except Exception:
            return  # 读取失败不阻塞：按当前快照进入验证
        if (
            job.last_started_at is not None
            and job.last_started_at >= armed_at
            and job.active_attempt_id is None
        ):
            return
        time.sleep(poll_seconds)


def _default_data_sync_retry_executor() -> RemediationExecutor:
    """生产执行器：复用治理控制面单例与后台 worker 同一执行路径。"""

    def service_factory() -> _GovernanceService:
        from src.runtime.api.data_governance_routes import get_data_governance_service

        return get_data_governance_service()

    def worker_factory() -> _SyncWorker:
        from src.data_platform.storage.postgresql.outpatient_governance_store import (
            OutpatientGovernanceStore,
        )
        from src.data_platform.storage.postgresql.outpatient_store import OutpatientPostgresStore
        from src.runtime.data_governance.worker import OutpatientSyncWorker, run_outpatient_job
        from src.semantic_layer.registry import get_semantic_registry

        service = service_factory()
        runner = partial(
            run_outpatient_job,
            governance_service=service,
            data_store=OutpatientPostgresStore(),
            semantic_registry=get_semantic_registry(),
        )
        return OutpatientSyncWorker(OutpatientGovernanceStore(), runner)

    return build_data_sync_retry_executor(service_factory, worker_factory)


def default_remediation_whitelist() -> tuple[RemediationSpec, ...]:
    """当前生效的修复白名单（代码内注册，不引入配置系统）。"""
    return (
        RemediationSpec(
            action_id="retry_data_sync",
            check_id="data_sync_failed",
            risk_level=RemediationRiskLevel.L1,
            description="重试失败/滞后的门诊同步任务（复用 data_governance 同步入口）",
            executor=_default_data_sync_retry_executor(),
        ),
    )
