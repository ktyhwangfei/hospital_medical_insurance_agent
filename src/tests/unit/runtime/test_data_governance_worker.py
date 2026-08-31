from datetime import datetime, time, timezone
from types import SimpleNamespace

from src.adapters.insurance_interface.outpatient_source import OutpatientSourceMode
from src.data_platform.outpatient_governance import (
    OutpatientSyncAttempt,
    OutpatientSyncJob,
    SyncJobStatus,
)
from src.runtime.data_governance.worker import OutpatientSyncWorker


NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)


def _job(mode=OutpatientSourceMode.CDC):
    return OutpatientSyncJob(
        source_id="bjybdb",
        source_mode=mode,
        status=SyncJobStatus.RUNNING,
        reconcile_time=time(2),
        active_attempt_id="attempt-1",
        created_at=NOW,
        updated_at=NOW,
    )


def _claim(mode=OutpatientSourceMode.CDC):
    job = _job(mode)
    return SimpleNamespace(
        job=job,
        attempt=OutpatientSyncAttempt(
            attempt_id="attempt-1",
            source_id=job.source_id,
            source_mode=mode,
            run_kind="baseline",
            status="running",
            started_at=NOW,
        ),
    )


class _Store:
    def __init__(self, claim):
        self.claim = claim
        self.completed = []
        self.failed = []

    def claim_due_job(self, _now):
        claim, self.claim = self.claim, None
        return claim

    def complete_job(self, *args, **kwargs):
        self.completed.append((args, kwargs))

    def fail_job(self, *args, **kwargs):
        self.failed.append((args, kwargs))


def test_worker_executes_claimed_job_and_records_success() -> None:
    store = _Store(_claim())
    sync_result = SimpleNamespace(batch_id="batch-1", row_count=3)
    worker = OutpatientSyncWorker(store, lambda _job, _kind, _now: sync_result)

    result = worker.run_one(now=NOW)

    assert result.status == "success"
    assert result.batch_id == "batch-1"
    assert store.completed[0][0][1] is sync_result
    assert store.failed == []


def test_worker_failure_keeps_checkpoint_and_hides_driver_error() -> None:
    store = _Store(_claim(OutpatientSourceMode.SCHEDULED_SQL))
    data_store = SimpleNamespace(checkpoint="2026-08-31T09:00:00+00:00")

    def fail(_job, _kind, _now):
        raise RuntimeError("driver-secret-text")

    result = OutpatientSyncWorker(store, fail).run_one(now=NOW)

    assert result.status == "failure"
    assert data_store.checkpoint == "2026-08-31T09:00:00+00:00"
    assert "driver-secret-text" not in store.failed[0][1]["safe_message"]


def test_worker_returns_idle_without_claim() -> None:
    result = OutpatientSyncWorker(_Store(None), lambda *_args: None).run_one(now=NOW)
    assert result.status == "idle"
