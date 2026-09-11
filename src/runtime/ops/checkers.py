"""健康运营检查器 — P0 数据域首批（issue #45，全部只读）。

检查器只读复用门诊数据治理控制面既有状态数据（连接探测结果、同步任务
状态），不改其任何表；payload 只携带脱敏安全字段（safe_* / 状态码 /
时间戳），不带出凭据与连接串。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Protocol

from src.data_platform.outpatient_governance import (
    ConnectionStatus,
    OutpatientDataSource,
    OutpatientSyncJob,
    SyncJobStatus,
)
from src.data_platform.storage.postgresql.outpatient_governance_store import (
    OutpatientGovernanceNotFoundError,
)
from src.domain.ops.models import FindingDraft, OpsAssetType, OpsSeverity

# 滞后判定宽限下限：应到未到超过 max(2×调度间隔, 15 分钟) 视为滞后
LAG_GRACE_FLOOR_MINUTES = 15


class GovernanceStatusReader(Protocol):
    """检查器对治理控制面的最小只读依赖（DataGovernanceService 已满足）。"""

    def list_sources(self) -> list[OutpatientDataSource]: ...

    def get_job(self, source_id: str) -> OutpatientSyncJob: ...


@dataclass(frozen=True)
class CheckSpec:
    """代码内检查器注册项（不引入 YAML 配置系统，YAGNI）。"""

    check_id: str
    asset_type: OpsAssetType
    description: str
    runner: Callable[[GovernanceStatusReader, datetime], list[FindingDraft]]


def check_data_sync(reader: GovernanceStatusReader, now: datetime) -> list[FindingDraft]:
    """门诊同步任务 failed / degraded / 滞后（应到未到超宽限期）。"""
    drafts: list[FindingDraft] = []
    for source in reader.list_sources():
        try:
            job = reader.get_job(source.source_id)
        except OutpatientGovernanceNotFoundError:
            continue  # 尚未配置同步任务的数据源不构成问题
        if job.status in (SyncJobStatus.FAILED, SyncJobStatus.DEGRADED):
            drafts.append(FindingDraft(
                asset_type=OpsAssetType.DATA,
                asset_id=source.source_id,
                check_id="data_sync_failed",
                severity=(
                    OpsSeverity.CRITICAL if job.status is SyncJobStatus.FAILED
                    else OpsSeverity.WARNING
                ),
                payload={
                    "problem": f"sync_job_{job.status.value}",
                    "job_status": job.status.value,
                    "last_error_code": job.last_error_code,
                    "last_started_at": job.last_started_at.isoformat()
                    if job.last_started_at else None,
                    "last_succeeded_at": job.last_succeeded_at.isoformat()
                    if job.last_succeeded_at else None,
                },
            ))
            continue
        if job.status in (SyncJobStatus.READY, SyncJobStatus.RUNNING):
            due_at = job.run_once_requested_at or job.next_run_at
            if due_at is None:
                continue
            grace = timedelta(minutes=max(
                2 * job.schedule_interval_minutes, LAG_GRACE_FLOOR_MINUTES,
            ))
            if now > due_at + grace:
                drafts.append(FindingDraft(
                    asset_type=OpsAssetType.DATA,
                    asset_id=source.source_id,
                    check_id="data_sync_failed",
                    severity=OpsSeverity.WARNING,
                    payload={
                        "problem": "sync_job_lagging",
                        "job_status": job.status.value,
                        "due_at": due_at.isoformat(),
                        "grace_minutes": int(grace.total_seconds() // 60),
                        "last_succeeded_at": job.last_succeeded_at.isoformat()
                        if job.last_succeeded_at else None,
                    },
                ))
    return drafts


def check_data_source(reader: GovernanceStatusReader, now: datetime) -> list[FindingDraft]:
    """数据源连接探测失败（connection_status == error；只读最近探测结果）。"""
    del now  # 判定不依赖当前时间；签名与 CheckSpec.runner 对齐
    drafts: list[FindingDraft] = []
    for source in reader.list_sources():
        if source.connection_status is not ConnectionStatus.ERROR:
            continue
        drafts.append(FindingDraft(
            asset_type=OpsAssetType.DATA,
            asset_id=source.source_id,
            check_id="data_source_down",
            severity=OpsSeverity.CRITICAL,
            payload={
                "problem": "connection_error",
                "safe_probe_message": source.safe_probe_message,
                "last_probed_at": source.last_probed_at.isoformat()
                if source.last_probed_at else None,
            },
        ))
    return drafts


OPS_CHECKS: tuple[CheckSpec, ...] = (
    CheckSpec(
        check_id="data_sync_failed",
        asset_type=OpsAssetType.DATA,
        description="门诊同步任务 failed/degraded/滞后",
        runner=check_data_sync,
    ),
    CheckSpec(
        check_id="data_source_down",
        asset_type=OpsAssetType.DATA,
        description="数据源连接探测失败",
        runner=check_data_source,
    ),
)
