"""门诊同步任务的单进程 PostgreSQL 调度 worker。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from pydantic import BaseModel

from src.adapters.insurance_interface.outpatient_cdc import (
    CdcRetentionGapError,
    SqlServerOutpatientCdcSource,
)
from src.adapters.insurance_interface.outpatient_polling import (
    SqlServerOutpatientPollingSource,
)
from src.adapters.insurance_interface.outpatient_source import (
    OutpatientSourceBatch,
    OutpatientSourceMode,
)
from src.data_platform.outpatient_governance import OutpatientSyncJob
from src.data_platform.outpatient_sync import OutpatientSyncService


class WorkerRunResult(BaseModel):
    status: str
    source_id: str | None = None
    attempt_id: str | None = None
    batch_id: str | None = None


class OutpatientSyncWorker:
    def __init__(self, store, sync_runner: Callable) -> None:
        self._store = store
        self._sync_runner = sync_runner

    def run_one(self, *, now: datetime | None = None) -> WorkerRunResult:
        now = now or datetime.now(timezone.utc)
        claimed = self._store.claim_due_job(now)
        if claimed is None:
            return WorkerRunResult(status="idle")
        try:
            result = self._sync_runner(
                claimed.job, claimed.attempt.run_kind, now
            )
        except Exception as exc:
            error_code, safe_message, degraded = _safe_sync_error(exc)
            self._store.fail_job(
                claimed,
                error_code=error_code,
                safe_message=safe_message,
                finished_at=now,
                degraded=degraded,
            )
            return WorkerRunResult(
                status="failure",
                source_id=claimed.job.source_id,
                attempt_id=claimed.attempt.attempt_id,
            )
        self._store.complete_job(
            claimed,
            result,
            finished_at=now,
            next_run_at=_next_run(claimed.job, now),
        )
        return WorkerRunResult(
            status="success",
            source_id=claimed.job.source_id,
            attempt_id=claimed.attempt.attempt_id,
            batch_id=result.batch_id,
        )


def run_outpatient_job(
    job: OutpatientSyncJob,
    run_kind: str,
    now: datetime,
    *,
    governance_service,
    data_store,
    semantic_registry,
):
    def connection_factory():
        return governance_service.open_source_connection(job.source_id)
    force_baseline = run_kind == "baseline"
    if job.source_mode is OutpatientSourceMode.CDC:
        source = SqlServerOutpatientCdcSource(connection_factory)
    else:
        polling = SqlServerOutpatientPollingSource(
            connection_factory,
            clock=lambda: now,
            lookback=timedelta(hours=job.lookback_hours),
            mapping=governance_service.effective_mapping(job.source_id),
        )
        if run_kind == "reconciliation":
            source = _FixedBatchSource(
                polling.read_time_window(now - timedelta(days=job.reconcile_days), now)
            )
        else:
            source = polling
    return OutpatientSyncService(
        source,
        data_store,
        semantic_registry,
        source_id=job.source_id,
    ).run_once(force_baseline=force_baseline)


class _FixedBatchSource:
    def __init__(self, batch: OutpatientSourceBatch) -> None:
        self._batch = batch

    def read(self, _checkpoint) -> OutpatientSourceBatch:
        return self._batch


def _next_run(job: OutpatientSyncJob, now: datetime) -> datetime:
    if job.source_mode is OutpatientSourceMode.CDC:
        return now + timedelta(seconds=job.cdc_poll_interval_seconds)
    return now + timedelta(minutes=job.schedule_interval_minutes)


def _safe_sync_error(exc: Exception) -> tuple[str, str, bool]:
    if isinstance(exc, CdcRetentionGapError):
        return "cdc_retention_gap", "CDC 保留窗口已失效，需重新执行基线", True
    return "sync_failed", "同步失败，请检查数据源连接和任务配置", False
