"""门诊数据治理控制面的 PostgreSQL 存储。"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.config.production import DATABASE_URL
from src.data_platform.outpatient_governance import (
    DataSourceCredential,
    ClaimedOutpatientSyncJob,
    OutpatientDataSource,
    OutpatientSyncAttempt,
    OutpatientSyncJob,
    OutpatientWorkerStatus,
    SyncJobStatus,
)
from src.data_platform.storage.postgresql.client import PostgreSQLClient


class OutpatientGovernanceNotFoundError(LookupError):
    pass


class OutpatientGovernanceConflictError(RuntimeError):
    pass


OUTPATIENT_GOVERNANCE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS outpatient_data_sources (
        source_id VARCHAR(64) PRIMARY KEY,
        hospital_code VARCHAR(64) NOT NULL,
        hospital_name VARCHAR(128) NOT NULL,
        name VARCHAR(128) NOT NULL,
        host VARCHAR(255) NOT NULL,
        port INTEGER NOT NULL CHECK(port BETWEEN 1 AND 65535),
        database_name VARCHAR(128) NOT NULL,
        schema_name VARCHAR(64) NOT NULL DEFAULT 'dbo',
        username VARCHAR(128) NOT NULL,
        credential_id VARCHAR(128) NOT NULL,
        connection_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
        cdc_status VARCHAR(32) NOT NULL DEFAULT 'not_checked',
        safe_probe_message TEXT,
        last_probed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS outpatient_data_source_credentials (
        credential_id VARCHAR(128) PRIMARY KEY,
        encrypted_password TEXT NOT NULL,
        secret_fingerprint VARCHAR(64) NOT NULL,
        endpoint_fingerprint VARCHAR(64) NOT NULL,
        revision INTEGER NOT NULL CHECK(revision >= 1),
        updated_by VARCHAR(128) NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS outpatient_sync_jobs (
        source_id VARCHAR(64) PRIMARY KEY REFERENCES outpatient_data_sources(source_id),
        source_mode VARCHAR(32) NOT NULL,
        status VARCHAR(32) NOT NULL,
        cdc_poll_interval_seconds INTEGER NOT NULL DEFAULT 45,
        schedule_interval_minutes INTEGER NOT NULL DEFAULT 5,
        lookback_hours INTEGER NOT NULL DEFAULT 2,
        reconcile_time TIME NOT NULL DEFAULT '02:00:00',
        reconcile_days INTEGER NOT NULL DEFAULT 30,
        revision INTEGER NOT NULL DEFAULT 1,
        baseline_required BOOLEAN NOT NULL DEFAULT TRUE,
        next_run_at TIMESTAMPTZ,
        run_once_requested_at TIMESTAMPTZ,
        active_attempt_id VARCHAR(64),
        last_started_at TIMESTAMPTZ,
        last_succeeded_at TIMESTAMPTZ,
        last_reconciled_at TIMESTAMPTZ,
        last_error_code VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS outpatient_sync_attempts (
        attempt_id VARCHAR(64) PRIMARY KEY,
        source_id VARCHAR(64) NOT NULL REFERENCES outpatient_data_sources(source_id),
        source_mode VARCHAR(32) NOT NULL,
        run_kind VARCHAR(32) NOT NULL,
        status VARCHAR(32) NOT NULL,
        started_at TIMESTAMPTZ NOT NULL,
        finished_at TIMESTAMPTZ,
        safe_error_code VARCHAR(64),
        safe_message VARCHAR(256),
        row_count INTEGER NOT NULL DEFAULT 0,
        batch_id VARCHAR(64)
    )""",
    "ALTER TABLE outpatient_data_sources ADD COLUMN IF NOT EXISTS hospital_code VARCHAR(64)",
    "ALTER TABLE outpatient_data_sources ADD COLUMN IF NOT EXISTS hospital_name VARCHAR(128)",
    "ALTER TABLE outpatient_data_sources ADD COLUMN IF NOT EXISTS name VARCHAR(128)",
    "ALTER TABLE outpatient_data_sources ADD COLUMN IF NOT EXISTS host VARCHAR(255)",
    "ALTER TABLE outpatient_data_sources ADD COLUMN IF NOT EXISTS port INTEGER",
    "ALTER TABLE outpatient_data_sources ADD COLUMN IF NOT EXISTS database_name VARCHAR(128)",
    "ALTER TABLE outpatient_data_sources ADD COLUMN IF NOT EXISTS schema_name VARCHAR(64) DEFAULT 'dbo'",
    "ALTER TABLE outpatient_data_sources ADD COLUMN IF NOT EXISTS username VARCHAR(128)",
    "ALTER TABLE outpatient_data_sources ADD COLUMN IF NOT EXISTS credential_id VARCHAR(128)",
    "ALTER TABLE outpatient_data_sources ADD COLUMN IF NOT EXISTS connection_status VARCHAR(32) DEFAULT 'unknown'",
    "ALTER TABLE outpatient_data_sources ADD COLUMN IF NOT EXISTS cdc_status VARCHAR(32) DEFAULT 'not_checked'",
    "ALTER TABLE outpatient_data_sources ADD COLUMN IF NOT EXISTS safe_probe_message TEXT",
    "ALTER TABLE outpatient_data_sources ADD COLUMN IF NOT EXISTS last_probed_at TIMESTAMPTZ",
    "ALTER TABLE outpatient_data_sources ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ",
    "ALTER TABLE outpatient_data_sources ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ",
    "ALTER TABLE outpatient_data_source_credentials ADD COLUMN IF NOT EXISTS encrypted_password TEXT",
    "ALTER TABLE outpatient_data_source_credentials ADD COLUMN IF NOT EXISTS secret_fingerprint VARCHAR(64)",
    "ALTER TABLE outpatient_data_source_credentials ADD COLUMN IF NOT EXISTS endpoint_fingerprint VARCHAR(64)",
    "ALTER TABLE outpatient_data_source_credentials ADD COLUMN IF NOT EXISTS revision INTEGER DEFAULT 1",
    "ALTER TABLE outpatient_data_source_credentials ADD COLUMN IF NOT EXISTS updated_by VARCHAR(128)",
    "ALTER TABLE outpatient_data_source_credentials ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS source_mode VARCHAR(32)",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS status VARCHAR(32)",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS cdc_poll_interval_seconds INTEGER DEFAULT 45",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS schedule_interval_minutes INTEGER DEFAULT 5",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS lookback_hours INTEGER DEFAULT 2",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS reconcile_time TIME DEFAULT '02:00:00'",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS reconcile_days INTEGER DEFAULT 30",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS revision INTEGER DEFAULT 1",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS baseline_required BOOLEAN DEFAULT TRUE",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS next_run_at TIMESTAMPTZ",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS run_once_requested_at TIMESTAMPTZ",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS active_attempt_id VARCHAR(64)",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS last_started_at TIMESTAMPTZ",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS last_succeeded_at TIMESTAMPTZ",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS last_reconciled_at TIMESTAMPTZ",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS last_error_code VARCHAR(64)",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ",
    "ALTER TABLE outpatient_sync_jobs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ",
    "ALTER TABLE outpatient_sync_attempts ADD COLUMN IF NOT EXISTS source_id VARCHAR(64)",
    "ALTER TABLE outpatient_sync_attempts ADD COLUMN IF NOT EXISTS source_mode VARCHAR(32)",
    "ALTER TABLE outpatient_sync_attempts ADD COLUMN IF NOT EXISTS run_kind VARCHAR(32)",
    "ALTER TABLE outpatient_sync_attempts ADD COLUMN IF NOT EXISTS status VARCHAR(32)",
    "ALTER TABLE outpatient_sync_attempts ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ",
    "ALTER TABLE outpatient_sync_attempts ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ",
    "ALTER TABLE outpatient_sync_attempts ADD COLUMN IF NOT EXISTS safe_error_code VARCHAR(64)",
    "ALTER TABLE outpatient_sync_attempts ADD COLUMN IF NOT EXISTS safe_message VARCHAR(256)",
    "ALTER TABLE outpatient_sync_attempts ADD COLUMN IF NOT EXISTS row_count INTEGER DEFAULT 0",
    "ALTER TABLE outpatient_sync_attempts ADD COLUMN IF NOT EXISTS batch_id VARCHAR(64)",
    "CREATE INDEX IF NOT EXISTS idx_outpatient_sync_jobs_due ON outpatient_sync_jobs(status, next_run_at)",
    "CREATE INDEX IF NOT EXISTS idx_outpatient_sync_attempts_source ON outpatient_sync_attempts(source_id, started_at DESC)",
)


class OutpatientGovernanceStore:
    def __init__(
        self,
        database_url: str | None = None,
        client: PostgreSQLClient | None = None,
    ) -> None:
        self._client = client or PostgreSQLClient(database_url or DATABASE_URL)
        self._schema_ready = False

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        for statement in OUTPATIENT_GOVERNANCE_SCHEMA:
            self._client.execute(statement)
        self._schema_ready = True

    def create_source_with_credential(
        self,
        source: OutpatientDataSource,
        credential: DataSourceCredential,
    ) -> None:
        self.ensure_schema()
        with self._client.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO outpatient_data_source_credentials
                       (credential_id, encrypted_password, secret_fingerprint,
                        endpoint_fingerprint, revision, updated_by, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        credential.credential_id, credential.encrypted_password,
                        credential.secret_fingerprint, credential.endpoint_fingerprint,
                        credential.revision, credential.updated_by, credential.updated_at,
                    ),
                )
                cursor.execute(
                    """INSERT INTO outpatient_data_sources
                       (source_id, hospital_code, hospital_name, name, host, port,
                        database_name, schema_name, username, credential_id,
                        connection_status, cdc_status, safe_probe_message,
                        last_probed_at, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s)""",
                    _source_values(source),
                )

    def list_sources(self) -> list[OutpatientDataSource]:
        self.ensure_schema()
        return [
            _source_from_row(row)
            for row in self._client.execute(_SOURCE_SELECT + " ORDER BY source_id")
        ]

    def get_source(self, source_id: str) -> OutpatientDataSource:
        self.ensure_schema()
        rows = self._client.execute(
            _SOURCE_SELECT + " WHERE source_id = %s", (source_id,)
        )
        if not rows:
            raise OutpatientGovernanceNotFoundError("门诊数据源不存在")
        return _source_from_row(rows[0])

    def update_source(self, source: OutpatientDataSource) -> None:
        self.ensure_schema()
        self._client.execute(
            """UPDATE outpatient_data_sources SET
                   hospital_code=%s, hospital_name=%s, name=%s, host=%s, port=%s,
                   database_name=%s, schema_name=%s, username=%s, credential_id=%s,
                   connection_status=%s, cdc_status=%s, safe_probe_message=%s,
                   last_probed_at=%s, updated_at=%s
               WHERE source_id=%s""",
            (
                source.hospital_code, source.hospital_name, source.name, source.host,
                source.port, source.database, source.schema_name, source.username,
                source.credential_id, source.connection_status.value, source.cdc_status.value,
                source.safe_probe_message, source.last_probed_at, source.updated_at,
                source.source_id,
            ),
        )

    def get_credential(self, credential_id: str) -> DataSourceCredential:
        self.ensure_schema()
        rows = self._client.execute(
            """SELECT credential_id, encrypted_password, secret_fingerprint,
                      endpoint_fingerprint, revision, updated_by, updated_at
               FROM outpatient_data_source_credentials WHERE credential_id=%s""",
            (credential_id,),
        )
        if not rows:
            raise OutpatientGovernanceNotFoundError("数据源凭据不存在")
        return DataSourceCredential.model_validate(rows[0])

    def rotate_credential(
        self,
        credential: DataSourceCredential,
        *,
        expected_revision: int,
    ) -> None:
        self.ensure_schema()
        with self._client.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT revision FROM outpatient_data_source_credentials WHERE credential_id=%s FOR UPDATE",
                    (credential.credential_id,),
                )
                row = cursor.fetchone()
                revision = row["revision"] if isinstance(row, dict) else row[0] if row else None
                if revision != expected_revision or credential.revision != expected_revision + 1:
                    raise OutpatientGovernanceConflictError("数据源凭据版本冲突")
                cursor.execute(
                    """UPDATE outpatient_data_source_credentials SET
                           encrypted_password=%s, secret_fingerprint=%s,
                           endpoint_fingerprint=%s, revision=%s, updated_by=%s, updated_at=%s
                       WHERE credential_id=%s""",
                    (
                        credential.encrypted_password, credential.secret_fingerprint,
                        credential.endpoint_fingerprint, credential.revision,
                        credential.updated_by, credential.updated_at, credential.credential_id,
                    ),
                )

    def get_job(self, source_id: str) -> OutpatientSyncJob:
        self.ensure_schema()
        rows = self._client.execute(
            "SELECT * FROM outpatient_sync_jobs WHERE source_id=%s", (source_id,)
        )
        if not rows:
            raise OutpatientGovernanceNotFoundError("门诊同步任务不存在")
        return OutpatientSyncJob.model_validate(rows[0])

    def save_job(
        self,
        job: OutpatientSyncJob,
        *,
        expected_revision: int | None = None,
    ) -> None:
        self.ensure_schema()
        values = _job_values(job)
        if expected_revision is None:
            self._client.execute(
                """INSERT INTO outpatient_sync_jobs
                   (source_id, source_mode, status, cdc_poll_interval_seconds,
                    schedule_interval_minutes, lookback_hours, reconcile_time,
                    reconcile_days, revision, baseline_required, next_run_at,
                    run_once_requested_at, active_attempt_id, last_started_at,
                    last_succeeded_at, last_reconciled_at, last_error_code,
                    created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (source_id) DO UPDATE SET
                       source_mode=EXCLUDED.source_mode, status=EXCLUDED.status,
                       cdc_poll_interval_seconds=EXCLUDED.cdc_poll_interval_seconds,
                       schedule_interval_minutes=EXCLUDED.schedule_interval_minutes,
                       lookback_hours=EXCLUDED.lookback_hours,
                       reconcile_time=EXCLUDED.reconcile_time,
                       reconcile_days=EXCLUDED.reconcile_days,
                       revision=EXCLUDED.revision,
                       baseline_required=EXCLUDED.baseline_required,
                       next_run_at=EXCLUDED.next_run_at,
                       run_once_requested_at=EXCLUDED.run_once_requested_at,
                       active_attempt_id=EXCLUDED.active_attempt_id,
                       last_started_at=EXCLUDED.last_started_at,
                       last_succeeded_at=EXCLUDED.last_succeeded_at,
                       last_reconciled_at=EXCLUDED.last_reconciled_at,
                       last_error_code=EXCLUDED.last_error_code,
                       updated_at=EXCLUDED.updated_at""",
                values,
            )
            return
        if job.revision != expected_revision + 1:
            raise OutpatientGovernanceConflictError("门诊同步任务版本冲突")
        rows = self._client.execute(
            """UPDATE outpatient_sync_jobs SET
                   source_mode=%s, status=%s, cdc_poll_interval_seconds=%s,
                   schedule_interval_minutes=%s, lookback_hours=%s, reconcile_time=%s,
                   reconcile_days=%s, revision=%s, baseline_required=%s, next_run_at=%s,
                   run_once_requested_at=%s, active_attempt_id=%s, last_started_at=%s,
                   last_succeeded_at=%s, last_reconciled_at=%s, last_error_code=%s,
                   updated_at=%s
               WHERE source_id=%s AND revision=%s RETURNING source_id""",
            (*values[1:17], values[18], job.source_id, expected_revision),
        )
        if not rows:
            raise OutpatientGovernanceConflictError("门诊同步任务版本冲突")

    def list_attempts(self, source_id: str, limit: int = 20) -> list[OutpatientSyncAttempt]:
        self.ensure_schema()
        rows = self._client.execute(
            """SELECT * FROM outpatient_sync_attempts WHERE source_id=%s
               ORDER BY started_at DESC LIMIT %s""",
            (source_id, limit),
        )
        return [OutpatientSyncAttempt.model_validate(row) for row in rows]

    def claim_due_job(self, now: datetime) -> ClaimedOutpatientSyncJob | None:
        self.ensure_schema()
        with self._client.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""SELECT {', '.join(_JOB_COLUMNS)}
                       FROM outpatient_sync_jobs
                       WHERE status IN ('ready', 'running')
                         AND COALESCE(run_once_requested_at, next_run_at) <= %s
                         AND active_attempt_id IS NULL
                       ORDER BY COALESCE(run_once_requested_at, next_run_at), source_id
                       FOR UPDATE SKIP LOCKED
                       LIMIT 1""",
                    (now,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                job = OutpatientSyncJob.model_validate(dict(zip(_JOB_COLUMNS, row)))
                attempt = OutpatientSyncAttempt(
                    attempt_id=str(uuid4()),
                    source_id=job.source_id,
                    source_mode=job.source_mode,
                    run_kind=_run_kind(job, now),
                    status="running",
                    started_at=now,
                )
                cursor.execute(
                    """UPDATE outpatient_sync_jobs SET
                           status='running', active_attempt_id=%s, last_started_at=%s,
                           updated_at=%s
                       WHERE source_id=%s""",
                    (attempt.attempt_id, now, now, job.source_id),
                )
                cursor.execute(
                    """INSERT INTO outpatient_sync_attempts
                       (attempt_id, source_id, source_mode, run_kind, status, started_at,
                        row_count)
                       VALUES (%s, %s, %s, %s, 'running', %s, 0)""",
                    (
                        attempt.attempt_id, attempt.source_id, attempt.source_mode.value,
                        attempt.run_kind, attempt.started_at,
                    ),
                )
                return ClaimedOutpatientSyncJob(
                    job=job.model_copy(update={
                        "status": SyncJobStatus.RUNNING,
                        "active_attempt_id": attempt.attempt_id,
                        "last_started_at": now,
                        "updated_at": now,
                    }),
                    attempt=attempt,
                )

    def complete_job(
        self,
        claimed: ClaimedOutpatientSyncJob,
        result,
        *,
        finished_at: datetime,
        next_run_at: datetime,
    ) -> None:
        with self._client.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE outpatient_sync_attempts SET
                           status='succeeded', finished_at=%s, row_count=%s, batch_id=%s
                       WHERE attempt_id=%s""",
                    (
                        finished_at, result.row_count, result.batch_id,
                        claimed.attempt.attempt_id,
                    ),
                )
                cursor.execute(
                    """UPDATE outpatient_sync_jobs SET
                           status='running', active_attempt_id=NULL, baseline_required=FALSE,
                           next_run_at=%s, run_once_requested_at=NULL,
                           last_succeeded_at=%s,
                           last_reconciled_at=CASE WHEN %s THEN %s ELSE last_reconciled_at END,
                           last_error_code=NULL, updated_at=%s
                       WHERE source_id=%s AND active_attempt_id=%s""",
                    (
                        next_run_at, finished_at,
                        claimed.attempt.run_kind == "reconciliation", finished_at,
                        finished_at, claimed.job.source_id, claimed.attempt.attempt_id,
                    ),
                )

    def fail_job(
        self,
        claimed: ClaimedOutpatientSyncJob,
        *,
        error_code: str,
        safe_message: str,
        finished_at: datetime,
        degraded: bool = False,
    ) -> None:
        status = "degraded" if degraded else "failed"
        with self._client.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE outpatient_sync_attempts SET
                           status='failed', finished_at=%s, safe_error_code=%s,
                           safe_message=%s
                       WHERE attempt_id=%s""",
                    (finished_at, error_code, safe_message, claimed.attempt.attempt_id),
                )
                cursor.execute(
                    """UPDATE outpatient_sync_jobs SET
                           status=%s, active_attempt_id=NULL, last_error_code=%s,
                           updated_at=%s
                       WHERE source_id=%s AND active_attempt_id=%s""",
                    (
                        status, error_code, finished_at, claimed.job.source_id,
                        claimed.attempt.attempt_id,
                    ),
                )

    def get_worker_status(self, now: datetime) -> OutpatientWorkerStatus:
        self.ensure_schema()
        counts = self._client.execute(
            """SELECT COUNT(*) AS total_jobs,
                      COUNT(*) FILTER (
                          WHERE status IN ('ready', 'running')
                            AND COALESCE(run_once_requested_at, next_run_at) <= %s
                      ) AS due_jobs
               FROM outpatient_sync_jobs""",
            (now,),
        )[0]
        attempts = self._client.execute(
            """SELECT status, started_at FROM outpatient_sync_attempts
               ORDER BY started_at DESC LIMIT 1"""
        )
        latest = attempts[0] if attempts else {}
        return OutpatientWorkerStatus(
            total_jobs=counts["total_jobs"],
            due_jobs=counts["due_jobs"],
            last_attempt_status=latest.get("status"),
            last_attempt_at=latest.get("started_at"),
        )


_SOURCE_SELECT = """SELECT source_id, hospital_code, hospital_name, name, host, port,
                            database_name, schema_name, username, credential_id,
                            TRUE AS credential_configured, connection_status, cdc_status,
                            safe_probe_message, last_probed_at, created_at, updated_at
                     FROM outpatient_data_sources"""

_JOB_COLUMNS = tuple(OutpatientSyncJob.model_fields)


def _source_values(source: OutpatientDataSource) -> tuple[Any, ...]:
    return (
        source.source_id, source.hospital_code, source.hospital_name, source.name,
        source.host, source.port, source.database, source.schema_name, source.username,
        source.credential_id, source.connection_status.value, source.cdc_status.value,
        source.safe_probe_message, source.last_probed_at, source.created_at, source.updated_at,
    )


def _source_from_row(row: dict[str, Any]) -> OutpatientDataSource:
    value = dict(row)
    value["database"] = value.pop("database_name")
    return OutpatientDataSource.model_validate(value)


def _job_values(job: OutpatientSyncJob) -> tuple[Any, ...]:
    return (
        job.source_id, job.source_mode.value, job.status.value,
        job.cdc_poll_interval_seconds, job.schedule_interval_minutes,
        job.lookback_hours, job.reconcile_time, job.reconcile_days, job.revision,
        job.baseline_required, job.next_run_at, job.run_once_requested_at,
        job.active_attempt_id, job.last_started_at, job.last_succeeded_at,
        job.last_reconciled_at, job.last_error_code, job.created_at, job.updated_at,
    )


def _run_kind(job: OutpatientSyncJob, now: datetime) -> str:
    if job.baseline_required:
        return "baseline"
    if job.source_mode.value != "scheduled_sql":
        return "incremental"
    local_now = now.astimezone(ZoneInfo("Asia/Shanghai"))
    last = (
        job.last_reconciled_at.astimezone(ZoneInfo("Asia/Shanghai"))
        if job.last_reconciled_at else None
    )
    if local_now.time().replace(tzinfo=None) >= job.reconcile_time and (
        last is None or last.date() < local_now.date()
    ):
        return "reconciliation"
    return "incremental"
