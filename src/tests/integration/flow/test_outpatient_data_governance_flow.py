from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from cryptography.fernet import Fernet

from src.adapters.insurance_interface.outpatient_cdc import CdcRetentionGapError
from src.adapters.insurance_interface.outpatient_source import (
    OUTPATIENT_SOURCE_SPECS,
    CheckpointKind,
    OutpatientChange,
    OutpatientCheckpoint,
    OutpatientSourceBatch,
    OutpatientSourceMode,
)
from src.data_platform.outpatient_governance import (
    CdcEnablementStatus,
    ClaimedOutpatientSyncJob,
    OutpatientSyncAttempt,
    SyncJobStatus,
)
from src.data_platform.outpatient_sync import OutpatientSyncService
from src.data_platform.storage.postgresql.outpatient_governance_store import (
    OutpatientGovernanceNotFoundError,
)
from src.runtime.api.data_governance_schemas import SaveSyncJobRequest
from src.runtime.data_governance.service import CreateDataSourceCommand, DataGovernanceService
from src.runtime.data_governance.worker import OutpatientSyncWorker


NOW = datetime(2026, 8, 31, 8, tzinfo=timezone.utc)


class _GovernanceStore:
    def __init__(self) -> None:
        self.sources = {}
        self.credentials = {}
        self.jobs = {}
        self.attempts = []

    def create_source_with_credential(self, source, credential):
        self.sources[source.source_id] = source
        self.credentials[credential.credential_id] = credential

    def get_source(self, source_id):
        return self.sources[source_id]

    def list_sources(self):
        return list(self.sources.values())

    def update_source(self, source):
        self.sources[source.source_id] = source

    def get_credential(self, credential_id):
        return self.credentials[credential_id]

    def get_job(self, source_id):
        try:
            return self.jobs[source_id]
        except KeyError as exc:
            raise OutpatientGovernanceNotFoundError(source_id) from exc

    def save_job(self, job, *, expected_revision=None):
        if expected_revision is not None:
            assert self.jobs[job.source_id].revision == expected_revision
        self.jobs[job.source_id] = job

    def claim_due_job(self, now):
        job = next((
            item for item in self.jobs.values()
            if item.status in {SyncJobStatus.READY, SyncJobStatus.RUNNING}
            and (item.run_once_requested_at or item.next_run_at) <= now
        ), None)
        if job is None:
            return None
        run_kind = "baseline" if job.baseline_required else "incremental"
        attempt = OutpatientSyncAttempt(
            attempt_id=str(uuid4()), source_id=job.source_id,
            source_mode=job.source_mode, run_kind=run_kind,
            status="running", started_at=now,
        )
        claimed_job = job.model_copy(update={
            "status": SyncJobStatus.RUNNING,
            "active_attempt_id": attempt.attempt_id,
            "last_started_at": now,
        })
        self.jobs[job.source_id] = claimed_job
        self.attempts.append(attempt)
        return ClaimedOutpatientSyncJob(job=claimed_job, attempt=attempt)

    def complete_job(self, claimed, result, *, finished_at, next_run_at):
        job = self.jobs[claimed.job.source_id]
        self.jobs[job.source_id] = job.model_copy(update={
            "status": SyncJobStatus.RUNNING,
            "active_attempt_id": None,
            "baseline_required": False,
            "next_run_at": next_run_at,
            "last_succeeded_at": finished_at,
        })
        self.attempts[-1] = self.attempts[-1].model_copy(update={
            "status": "succeeded", "finished_at": finished_at,
            "row_count": result.row_count, "batch_id": result.batch_id,
        })

    def fail_job(self, claimed, *, error_code, safe_message, finished_at, degraded=False):
        job = self.jobs[claimed.job.source_id]
        self.jobs[job.source_id] = job.model_copy(update={
            "status": SyncJobStatus.DEGRADED if degraded else SyncJobStatus.FAILED,
            "active_attempt_id": None,
            "last_error_code": error_code,
        })
        self.attempts[-1] = self.attempts[-1].model_copy(update={
            "status": "failed", "finished_at": finished_at,
            "safe_error_code": error_code, "safe_message": safe_message,
        })


class _ProjectionStore:
    def __init__(self) -> None:
        self.checkpoint = None
        self.rows = {capture: {} for capture in OUTPATIENT_SOURCE_SPECS}
        self.published = {}
        self.operations = []
        self.fail_next = False

    def ensure_schema(self):
        return None

    def check_schema(self):
        return True

    def get_checkpoint(self, _source_id):
        return self.checkpoint

    def load_all_projection_rows(self):
        return self._rows()

    def load_projection_rows_for_window(self, _start, _end):
        return self._rows()

    def load_projection_rows(self, trade_nos):
        return {
            capture: tuple(
                deepcopy(row) for row in rows.values()
                if row.get("T_TradeNo") in trade_nos
            )
            for capture, rows in self.rows.items()
        }

    def publish_batch(self, **payload):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("postgres unavailable with secret details")
        batch = payload["batch"]
        identity = (
            payload["source_id"], batch.mode.value, batch.checkpoint.kind.value,
            batch.checkpoint.value, payload["execution_mode"],
        )
        if identity in self.published:
            return self.published[identity]
        staged = deepcopy(self.rows)
        for change in batch.changes:
            spec = OUTPATIENT_SOURCE_SPECS[change.capture_instance]
            key = tuple(change.payload[column] for column in spec.key_columns)
            if change.operation == 1:
                staged[change.capture_instance].pop(key, None)
            else:
                staged[change.capture_instance][key] = deepcopy(change.payload)
        published = SimpleNamespace(
            batch_id=f"batch-{len(self.published) + 1}",
            row_count=len(batch.changes), published_at=NOW,
        )
        self.rows = staged
        self.checkpoint = batch.checkpoint
        self.operations.append(tuple(change.operation for change in batch.changes))
        self.published[identity] = published
        return published

    def _rows(self):
        return {
            capture: tuple(deepcopy(row) for row in rows.values())
            for capture, rows in self.rows.items()
        }


class _ProbeConnection:
    def __init__(self, state):
        self.state = state
        self.description = []
        self.rows = []

    def cursor(self):
        return self

    def execute(self, sql, *_params):
        if sql == "SELECT 1":
            self.description, self.rows = [("value",)], [(1,)]
        elif "SELECT is_cdc_enabled" in sql:
            self.description, self.rows = [("is_cdc_enabled",)], [(self.state["enabled"],)]
        elif "cdc.captured_columns" in sql:
            self.description = [("capture_instance",), ("column_name",)]
            self.rows = [
                (capture, column)
                for capture, spec in OUTPATIENT_SOURCE_SPECS.items()
                for column in spec.columns
            ]
        elif "msdb.dbo.cdc_jobs" in sql:
            self.description, self.rows = [("retention",)], [(4320,)]
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def close(self):
        return None


class _BatchSource:
    def __init__(self, item):
        self.item = item

    def read(self, _checkpoint):
        if isinstance(self.item, Exception):
            raise self.item
        return self.item


class _Registry:
    def get_object(self, _code):
        return SimpleNamespace(status="published", current_version="1")

    def get_object_version(self, _code, _version):
        return SimpleNamespace(snapshot={"queryable": True})


def _trade(trade_no: str, amount: str) -> dict:
    total = Decimal(amount)
    return {
        "T_TradeNo": trade_no, "T_TradeDate": NOW, "T_State": 3,
        "NP_Settle_State": "1", "T_FeeAll": total, "T_FeeIn": total,
        "T_FeeOut": Decimal("0"), "T_FundPay": total,
        "T_SelfPayAll": Decimal("0"),
    }


def _snapshot(mode, kind, value, rows, *, baseline, scope=()):
    return OutpatientSourceBatch(
        mode=mode,
        checkpoint=OutpatientCheckpoint(kind, value, NOW),
        snapshot_rows={
            "dbo_o_Trade": tuple(rows),
            "dbo_o_FeeItem": (),
            "dbo_o_Diagnose": (),
        },
        is_baseline=baseline,
        scope_trade_nos=frozenset(scope),
        window_start=NOW - timedelta(hours=2) if mode is OutpatientSourceMode.SCHEDULED_SQL else None,
        window_end=NOW if mode is OutpatientSourceMode.SCHEDULED_SQL else None,
    )


def _change(trade_no: str, amount: str) -> OutpatientChange:
    return OutpatientChange(
        capture_instance="dbo_o_Trade", source_cursor=b"\x30\x01",
        operation=4, commit_time=NOW, source_key=(trade_no,),
        payload=_trade(trade_no, amount),
    )


def test_governed_dual_mode_sync_and_failure_recovery(monkeypatch) -> None:
    monkeypatch.setenv("DATA_GOVERNANCE_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    governance_store = _GovernanceStore()
    projection_store = _ProjectionStore()
    probe_state = {"enabled": False}
    service = DataGovernanceService(
        governance_store, projection_store,
        lambda _source, _password: _ProbeConnection(probe_state),
    )
    source = service.create_source(CreateDataSourceCommand(
        source_id="hospital-outpatient", hospital_code="H001", hospital_name="示例医院",
        name="门诊医保库", host="sqlserver.internal", database="bjybdb",
        username="cdc_reader", credential_id="credential.hospital-outpatient",
        password="never-return-this-password",
    ), actor="admin")
    assert "never-return-this-password" not in source.model_dump_json()
    assert service.probe_cdc(source.source_id).status == "waiting_dba"
    assert governance_store.get_source(source.source_id).cdc_status is CdcEnablementStatus.WAITING_DBA

    job = service.save_job_config(source.source_id, SaveSyncJobRequest(
        source_mode="scheduled_sql", expected_revision=1,
        schedule_interval_minutes=5, lookback_hours=2,
    ), actor="admin")
    service.start_job(source.source_id, actor="admin")
    batches = {
        OutpatientSourceMode.SCHEDULED_SQL: [
            _snapshot(
                OutpatientSourceMode.SCHEDULED_SQL, CheckpointKind.TIME_WINDOW,
                NOW.isoformat(), [_trade("T1", "10"), _trade("T2", "20")], baseline=True,
            ),
            _snapshot(
                OutpatientSourceMode.SCHEDULED_SQL, CheckpointKind.TIME_WINDOW,
                (NOW + timedelta(minutes=5)).isoformat(),
                [_trade("T1", "11"), _trade("T3", "30")],
                baseline=False, scope=("T1", "T2", "T3"),
            ),
        ],
        OutpatientSourceMode.CDC: [],
    }

    def run(job, run_kind, _now):
        item = batches[job.source_mode].pop(0)
        return OutpatientSyncService(
            _BatchSource(item), projection_store, _Registry(), source_id=job.source_id,
        ).run_once(force_baseline=run_kind == "baseline")

    worker = OutpatientSyncWorker(governance_store, run)
    first = worker.run_one(now=datetime.now(timezone.utc) + timedelta(minutes=1))
    second = worker.run_one(now=datetime.now(timezone.utc) + timedelta(minutes=10))
    assert first.status == second.status == "success"
    assert set(projection_store.operations[-1]) == {1, 2, 4}
    assert set(projection_store.rows["dbo_o_Trade"]) == {("T1",), ("T3",)}

    service.pause_job(source.source_id, actor="admin")
    probe_state["enabled"] = True
    assert service.probe_cdc(source.source_id).status == "ready"
    job = service.save_job_config(source.source_id, SaveSyncJobRequest(
        source_mode="cdc", expected_revision=governance_store.get_job(source.source_id).revision,
        confirm_mode_switch=True, cdc_poll_interval_seconds=45,
    ), actor="admin")
    assert job.baseline_required is True
    service.start_job(source.source_id, actor="admin")
    cdc_baseline = _snapshot(
        OutpatientSourceMode.CDC, CheckpointKind.LSN, "20", [_trade("T4", "40")],
        baseline=True,
    )
    cdc_increment = OutpatientSourceBatch(
        mode=OutpatientSourceMode.CDC,
        checkpoint=OutpatientCheckpoint(CheckpointKind.LSN, "30", NOW),
        changes=(_change("T4", "41"),),
    )
    batches[OutpatientSourceMode.CDC].extend([cdc_baseline, cdc_increment, cdc_increment])
    worker.run_one(now=datetime.now(timezone.utc) + timedelta(minutes=20))
    incremental = worker.run_one(now=datetime.now(timezone.utc) + timedelta(minutes=21))
    replay = worker.run_one(now=datetime.now(timezone.utc) + timedelta(minutes=22))
    assert incremental.batch_id == replay.batch_id
    assert projection_store.checkpoint.value == "30"

    batches[OutpatientSourceMode.CDC].append(CdcRetentionGapError("expired LSN"))
    degraded = worker.run_one(now=datetime.now(timezone.utc) + timedelta(minutes=23))
    assert degraded.status == "failure"
    assert governance_store.get_job(source.source_id).status is SyncJobStatus.DEGRADED
    assert governance_store.get_job(source.source_id).last_error_code == "cdc_retention_gap"

    current = governance_store.get_job(source.source_id)
    governance_store.jobs[source.source_id] = current.model_copy(update={
        "status": SyncJobStatus.READY,
        "next_run_at": datetime.now(timezone.utc),
        "baseline_required": False,
    })
    batches[OutpatientSourceMode.CDC].append(OutpatientSourceBatch(
        mode=OutpatientSourceMode.CDC,
        checkpoint=OutpatientCheckpoint(CheckpointKind.LSN, "40", NOW),
        changes=(_change("T4", "42"),),
    ))
    projection_store.fail_next = True
    failed = worker.run_one(now=datetime.now(timezone.utc) + timedelta(minutes=24))
    assert failed.status == "failure"
    assert projection_store.checkpoint.value == "30"
    assert "secret" not in (governance_store.attempts[-1].safe_message or "")
