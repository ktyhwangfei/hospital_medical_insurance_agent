"""门诊数据治理 API 的公开契约。"""
from __future__ import annotations

from datetime import datetime, time
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

from src.data_platform.outpatient_governance import (
    CdcEnablementStatus,
    CaptureMapping,
    ConnectionStatus,
    OutpatientDataSource,
    OutpatientSourceMapping,
    OutpatientSyncAttempt,
    OutpatientSyncJob,
    PostgresTargetStatus,
)
from src.runtime.api.schemas import AgentResponse
from src.runtime.data_governance.service import (
    MappingSqlPreview,
    SaveMappingRequest,
    SourceColumnDetail,
    SourceTableSummary,
)

class DataGovernancePrincipal(BaseModel):
    user_id: str
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)


class DataSourceCredentialInput(BaseModel):
    credential_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    password: SecretStr = Field(min_length=1, max_length=4096)


class RotateDataSourceCredentialRequest(DataSourceCredentialInput):
    expected_revision: int = Field(ge=1)


class CreateDataSourceRequest(BaseModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$")
    hospital_code: str = Field(min_length=1, max_length=64)
    hospital_name: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=1433, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    schema_name: Literal["dbo"] = "dbo"
    username: str = Field(min_length=1, max_length=128)
    credential: DataSourceCredentialInput


class UpdateDataSourceRequest(BaseModel):
    hospital_code: str | None = Field(default=None, min_length=1, max_length=64)
    hospital_name: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, min_length=1, max_length=128)
    username: str | None = Field(default=None, min_length=1, max_length=128)


class SaveSyncJobRequest(BaseModel):
    source_mode: Literal["cdc", "scheduled_sql"]
    expected_revision: int = Field(ge=1)
    confirm_mode_switch: bool = False
    cdc_poll_interval_seconds: int = Field(default=45, ge=30, le=60)
    schedule_interval_minutes: int = Field(default=5, ge=1, le=1440)
    lookback_hours: int = Field(default=2, ge=1, le=168)
    reconcile_time: time = time(2)
    reconcile_days: int = Field(default=30, ge=1, le=365)


class DataGovernanceIssue(BaseModel):
    code: str
    severity: Literal["warning", "blocking"]
    message: str
    source_id: str | None = None


class DataGovernanceSourceStatus(BaseModel):
    source_id: str
    hospital_code: str
    hospital_name: str
    name: str
    credential_configured: bool
    connection_status: ConnectionStatus
    cdc_status: CdcEnablementStatus
    sync_status: str | None = None
    source_mode: str | None = None
    next_run_at: datetime | None = None
    last_succeeded_at: datetime | None = None
    quality_status: str | None = None
    latest_latency_seconds: float | None = None

    @classmethod
    def from_source(
        cls,
        source: OutpatientDataSource,
        job: OutpatientSyncJob | None = None,
        *,
        quality_status: str | None = None,
        latest_latency_seconds: float | None = None,
    ) -> "DataGovernanceSourceStatus":
        return cls(
            source_id=source.source_id,
            hospital_code=source.hospital_code,
            hospital_name=source.hospital_name,
            name=source.name,
            credential_configured=source.credential_configured,
            connection_status=source.connection_status,
            cdc_status=source.cdc_status,
            sync_status=job.status.value if job else None,
            source_mode=job.source_mode.value if job else None,
            next_run_at=job.next_run_at if job else None,
            last_succeeded_at=job.last_succeeded_at if job else None,
            quality_status=quality_status,
            latest_latency_seconds=latest_latency_seconds,
        )


class DataGovernanceOverview(BaseModel):
    platform_ready: bool = False
    postgresql: PostgresTargetStatus
    data_source_count: int = Field(ge=0)
    running_job_count: int = Field(ge=0)
    issue_count: int = Field(ge=0)
    latest_latency_seconds: float | None = None
    sources: list[DataGovernanceSourceStatus] = Field(default_factory=list)
    issues: list[DataGovernanceIssue] = Field(default_factory=list)
    recent_runs: list[OutpatientSyncAttempt] = Field(default_factory=list)


class DataSourceListResult(BaseModel):
    items: list[OutpatientDataSource] = Field(default_factory=list)


class SyncRunListResult(BaseModel):
    items: list[OutpatientSyncAttempt] = Field(default_factory=list)


class ConnectionProbeResult(BaseModel):
    status: ConnectionStatus
    error_code: str | None = None
    safe_message: str
    checked_at: datetime


class CdcProbeResult(BaseModel):
    status: str
    database_enabled: bool
    ready_captures: list[str] = Field(default_factory=list)
    missing_captures: list[str] = Field(default_factory=list)
    retention_minutes: int | None = None
    safe_message: str
    checked_at: datetime


class DataGovernanceOverviewResponse(AgentResponse):
    scenario: Literal["data_governance"] = "data_governance"
    status: Literal["success"] = "success"
    result: DataGovernanceOverview


class DataSourceListResponse(AgentResponse):
    scenario: Literal["data_governance"] = "data_governance"
    status: Literal["success"] = "success"
    result: DataSourceListResult


class DataSourceResponse(AgentResponse):
    scenario: Literal["data_governance"] = "data_governance"
    status: Literal["success"] = "success"
    result: OutpatientDataSource


class ConnectionProbeResponse(AgentResponse):
    scenario: Literal["data_governance"] = "data_governance"
    status: Literal["success"] = "success"
    result: ConnectionProbeResult


class CdcProbeResponse(AgentResponse):
    scenario: Literal["data_governance"] = "data_governance"
    status: Literal["success"] = "success"
    result: CdcProbeResult


class PostgresTargetResponse(AgentResponse):
    scenario: Literal["data_governance"] = "data_governance"
    status: Literal["success"] = "success"
    result: PostgresTargetStatus


class SyncJobResponse(AgentResponse):
    scenario: Literal["data_governance"] = "data_governance"
    status: Literal["success"] = "success"
    result: OutpatientSyncJob


class SyncRunListResponse(AgentResponse):
    scenario: Literal["data_governance"] = "data_governance"
    status: Literal["success"] = "success"
    result: SyncRunListResult


class SourceTableListResponse(AgentResponse):
    scenario: Literal["data_governance"] = "data_governance"
    status: Literal["success"] = "success"
    result: list[SourceTableSummary]


class SourceColumnListResponse(AgentResponse):
    scenario: Literal["data_governance"] = "data_governance"
    status: Literal["success"] = "success"
    result: list[SourceColumnDetail]


class MappingResponse(AgentResponse):
    scenario: Literal["data_governance"] = "data_governance"
    status: Literal["success"] = "success"
    result: OutpatientSourceMapping


class SqlPreviewResponse(AgentResponse):
    scenario: Literal["data_governance"] = "data_governance"
    status: Literal["success"] = "success"
    result: MappingSqlPreview


class SqlPreviewRequest(BaseModel):
    """草稿预览：携带未保存的 capture 映射列表。"""

    captures: list[CaptureMapping] = Field(min_length=3, max_length=3)


__all__ = [
    "MappingResponse",
    "SaveMappingRequest",
    "SourceColumnListResponse",
    "SourceTableListResponse",
    "SqlPreviewResponse",
]
