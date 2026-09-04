"""门诊数据治理控制面的稳定模型。"""
from __future__ import annotations

import re
from datetime import datetime, time, timezone
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from src.adapters.insurance_interface.outpatient_source import OutpatientSourceMode

# 契约锚点字段（下游语义层直引，不可改名；映射只能改源列侧）
TRADE_NO_FIELD = "T_TradeNo"
TIME_FIELD = "T_TradeDate"


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
    credential_revision: int | None = Field(default=None, ge=1)
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


# SQL Server 安全标识符（防 SQL 注入：映射名直接拼入 SQL，此处是信任边界）
_IDENTIFIER_PATTERN = r"^[A-Za-z_][A-Za-z0-9_@$#]{0,127}$"
_IDENTIFIER = Field(pattern=_IDENTIFIER_PATTERN)


class CaptureMapping(BaseModel):
    """单张源表 → 契约 capture 的映射（契约字段名为锚点，源列仅出现在 SELECT 别名与 WHERE）。

    契约锚点 T_TradeNo/T_TradeDate 固定不可改名（下游语义层直引）；
    可配的是：源表名、schema、每个契约字段对应的源列、主键由哪些契约字段组成。
    """

    capture: str = Field(pattern=r"^dbo_o_(Trade|FeeItem|Diagnose)$")
    table_schema: str = Field(default="dbo", pattern=r"^[A-Za-z_][A-Za-z0-9_@$#]{0,127}$")
    table_name: str = _IDENTIFIER
    key_fields: tuple[str, ...] = Field(min_length=1)  # 主键（契约字段名，必须 ⊆ column_map）
    column_map: dict[str, str] = Field(min_length=1)  # 契约字段 → 源列

    @model_validator(mode="after")
    def _validate_mapping(self) -> "CaptureMapping":
        for source_column in self.column_map.values():
            if not re.match(_IDENTIFIER_PATTERN, source_column):
                raise ValueError(f"非法源列名: {source_column}")
        missing_keys = [field for field in self.key_fields if field not in self.column_map]
        if missing_keys:
            raise ValueError(f"主键字段未映射源列: {missing_keys}")
        if TRADE_NO_FIELD not in self.column_map:
            raise ValueError("契约锚点 T_TradeNo 必须映射源列（父子表关联）")
        if self.capture == "dbo_o_Trade" and TIME_FIELD not in self.column_map:
            raise ValueError("交易表必须映射 T_TradeDate 源列（增量时间窗口）")
        return self


class OutpatientSourceMapping(BaseModel):
    """一个数据源的三张源表映射；无存储行时回退 default_source_mapping（当前写死契约）。"""

    source_id: str = Field(min_length=1, max_length=64)
    captures: dict[str, CaptureMapping]
    revision: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime


def default_source_mapping(source_id: str, now: datetime | None = None) -> OutpatientSourceMapping:
    """从固定契约规格生成默认映射（与历史硬编码行为逐字等价）。"""
    from src.adapters.insurance_interface.outpatient_source import OUTPATIENT_SOURCE_SPECS

    now = now or datetime.now(timezone.utc)
    captures: dict[str, CaptureMapping] = {}
    for capture, spec in OUTPATIENT_SOURCE_SPECS.items():
        captures[capture] = CaptureMapping(
            capture=capture,
            table_schema="dbo",
            table_name=spec.table_name,
            key_fields=tuple(spec.key_columns),
            column_map={column: column for column in spec.columns},
        )
    return OutpatientSourceMapping(
        source_id=source_id, captures=captures, revision=1, created_at=now, updated_at=now
    )


class ClaimedOutpatientSyncJob(BaseModel):
    job: OutpatientSyncJob
    attempt: OutpatientSyncAttempt


class OutpatientWorkerStatus(BaseModel):
    total_jobs: int = Field(ge=0)
    due_jobs: int = Field(ge=0)
    last_attempt_status: str | None = None
    last_attempt_at: datetime | None = None
