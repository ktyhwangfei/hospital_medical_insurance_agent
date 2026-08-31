"""门诊数据治理控制面的稳定模型。"""
from __future__ import annotations

from datetime import datetime, time
from enum import StrEnum

from pydantic import BaseModel, Field

from src.adapters.insurance_interface.outpatient_source import OutpatientSourceMode


class ConnectionStatus(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    ERROR = "error"


class CdcEnablementStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    NOT_CHECKED = "not_checked"
    WAITING_DBA = "waiting_dba"
    READY = "ready"
    INVALID = "invalid"


class SyncJobStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    DEGRADED = "degraded"
    FAILED = "failed"


class OutpatientDataSource(BaseModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$")
    hospital_code: str = Field(min_length=1, max_length=64)
    hospital_name: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=1433, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    schema_name: str = Field(default="dbo", pattern=r"^[A-Za-z0-9_]+$")
    username: str = Field(min_length=1, max_length=128)
    credential_id: str = Field(min_length=1, max_length=128)
    credential_configured: bool = True
    connection_status: ConnectionStatus = ConnectionStatus.UNKNOWN
    cdc_status: CdcEnablementStatus = CdcEnablementStatus.NOT_CHECKED
    safe_probe_message: str | None = Field(default=None, max_length=256)
    last_probed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DataSourceCredential(BaseModel):
    credential_id: str = Field(min_length=1, max_length=128)
    encrypted_password: str = Field(min_length=1)
    secret_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    endpoint_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: int = Field(ge=1)
    updated_by: str = Field(min_length=1, max_length=128)
    updated_at: datetime


class OutpatientSyncJob(BaseModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$")
    source_mode: OutpatientSourceMode
    status: SyncJobStatus = SyncJobStatus.DRAFT
    cdc_poll_interval_seconds: int = Field(default=45, ge=30, le=60)
    schedule_interval_minutes: int = Field(default=5, ge=1, le=1440)
    lookback_hours: int = Field(default=2, ge=1, le=168)
    reconcile_time: time = time(2)
    reconcile_days: int = Field(default=30, ge=1, le=365)
    revision: int = Field(default=1, ge=1)
    baseline_required: bool = True
    next_run_at: datetime | None = None
    run_once_requested_at: datetime | None = None
    active_attempt_id: str | None = None
    last_started_at: datetime | None = None
    last_succeeded_at: datetime | None = None
    last_reconciled_at: datetime | None = None
    last_error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class OutpatientSyncAttempt(BaseModel):
    attempt_id: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=64)
    source_mode: OutpatientSourceMode
    run_kind: str = Field(pattern=r"^(baseline|incremental|reconciliation|manual)$")
    status: str = Field(pattern=r"^(running|succeeded|failed)$")
    started_at: datetime
    finished_at: datetime | None = None
    safe_error_code: str | None = Field(default=None, max_length=64)
    safe_message: str | None = Field(default=None, max_length=256)
    row_count: int = Field(default=0, ge=0)
    batch_id: str | None = None


class PostgresTargetStatus(BaseModel):
    connection_status: ConnectionStatus
    schema_ready: bool
    safe_message: str = Field(max_length=256)
    checked_at: datetime


class ClaimedOutpatientSyncJob(BaseModel):
    job: OutpatientSyncJob
    attempt: OutpatientSyncAttempt


class OutpatientWorkerStatus(BaseModel):
    total_jobs: int = Field(ge=0)
    due_jobs: int = Field(ge=0)
    last_attempt_status: str | None = None
    last_attempt_at: datetime | None = None
