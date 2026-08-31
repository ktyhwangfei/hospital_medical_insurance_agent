"""门诊数据源配置、连接检测与 CDC 检测应用服务。"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field, SecretStr

from src.adapters.insurance_interface.outpatient_cdc import (
    OutpatientCdcProbe,
    SourceContractMismatchError,
    SqlServerOutpatientCdcSource,
)
from src.data_platform.outpatient_governance import (
    CdcEnablementStatus,
    ConnectionStatus,
    OutpatientDataSource,
    OutpatientSyncJob,
    SyncJobStatus,
    PostgresTargetStatus,
)
from src.security.data_source_credentials import (
    DataSourceCredentialVault,
    data_source_endpoint,
)
from src.data_platform.storage.postgresql.outpatient_governance_store import (
    OutpatientGovernanceNotFoundError,
)


class CdcNotReadyError(RuntimeError):
    pass


class SyncJobInvalidStateError(RuntimeError):
    pass


class CreateDataSourceCommand(BaseModel):
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
    password: SecretStr


class DataSourceConnectionProbe(BaseModel):
    status: ConnectionStatus
    error_code: str | None = None
    safe_message: str = Field(max_length=256)
    checked_at: datetime


class DataGovernanceService:
    def __init__(
        self,
        store,
        outpatient_store,
        connection_factory: Callable[[OutpatientDataSource, str], Any],
        vault: DataSourceCredentialVault | None = None,
    ) -> None:
        self._store = store
        self._outpatient_store = outpatient_store
        self._connection_factory = connection_factory
        self._vault = vault or DataSourceCredentialVault()

    def create_source(
        self,
        command: CreateDataSourceCommand,
        actor: str,
    ) -> OutpatientDataSource:
        now = datetime.now(timezone.utc)
        endpoint = data_source_endpoint(
            command.host, command.port, command.database, command.username
        )
        credential = self._vault.seal(
            credential_id=command.credential_id,
            password=command.password.get_secret_value(),
            endpoint=endpoint,
            actor=actor,
            revision=1,
        )
        source = OutpatientDataSource(
            source_id=command.source_id,
            hospital_code=command.hospital_code,
            hospital_name=command.hospital_name,
            name=command.name,
            host=command.host,
            port=command.port,
            database=command.database,
            schema_name=command.schema_name,
            username=command.username,
            credential_id=command.credential_id,
            credential_configured=True,
            created_at=now,
            updated_at=now,
        )
        self._store.create_source_with_credential(source, credential)
        return source

    def list_sources(self) -> list[OutpatientDataSource]:
        return [self._with_credential_status(source) for source in self._store.list_sources()]

    def overview(self):
        from src.runtime.api.data_governance_schemas import (
            DataGovernanceOverview,
            DataGovernanceSourceStatus,
        )

        sources = self.list_sources()
        statuses = []
        issues = []
        recent_runs = []
        latencies = []
        running_jobs = 0
        for source in sources:
            try:
                job = self._store.get_job(source.source_id)
            except OutpatientGovernanceNotFoundError:
                job = None
            sync_status = self._outpatient_store.get_sync_status(source.source_id)
            latency = sync_status.last_non_empty_latency_seconds
            if latency is not None:
                latencies.append(latency)
            statuses.append(DataGovernanceSourceStatus.from_source(
                source,
                job,
                quality_status=sync_status.quality_status,
                latest_latency_seconds=latency,
            ))
            if job and job.status in {SyncJobStatus.READY, SyncJobStatus.RUNNING}:
                running_jobs += 1
            issues.extend(_source_issues(source, job, sync_status.quality_status))
            recent_runs.extend(self._store.list_attempts(source.source_id, limit=5))
        recent_runs.sort(key=lambda item: item.started_at, reverse=True)
        return DataGovernanceOverview(
            data_source_count=len(sources),
            running_job_count=running_jobs,
            issue_count=len(issues),
            latest_latency_seconds=max(latencies) if latencies else None,
            sources=statuses,
            issues=issues,
            recent_runs=recent_runs[:10],
        )

    def update_source_config(self, source_id: str, request, actor: str) -> OutpatientDataSource:
        del actor
        source = self._store.get_source(source_id)
        now = datetime.now(timezone.utc)
        changes = request.model_dump(exclude_none=True, exclude_unset=True)
        endpoint_changed = bool({"host", "port", "database", "username"} & changes.keys())
        updated = source.model_copy(update={
            **changes,
            **({
                "connection_status": ConnectionStatus.UNKNOWN,
                "cdc_status": CdcEnablementStatus.NOT_CHECKED,
                "safe_probe_message": None,
            } if endpoint_changed else {}),
            "updated_at": now,
        })
        self._store.update_source(updated)
        return self._with_credential_status(updated)

    def rotate_credential(
        self,
        source_id: str,
        credential_id: str,
        password: str,
        expected_revision: int,
        actor: str,
    ) -> OutpatientDataSource:
        source = self._store.get_source(source_id)
        if credential_id != source.credential_id:
            raise SyncJobInvalidStateError("凭据标识与数据源不匹配")
        endpoint = data_source_endpoint(
            source.host, source.port, source.database, source.username
        )
        credential = self._vault.seal(
            credential_id=credential_id,
            password=password,
            endpoint=endpoint,
            actor=actor,
            revision=expected_revision + 1,
        )
        self._store.rotate_credential(credential, expected_revision=expected_revision)
        return source.model_copy(update={
            "credential_configured": True,
            "credential_revision": credential.revision,
        })

    def probe_connection(self, source_id: str) -> DataSourceConnectionProbe:
        source = self._store.get_source(source_id)
        checked_at = datetime.now(timezone.utc)
        connection = None
        try:
            password = self._password(source)
            connection = self._connection_factory(source, password)
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            if cursor.fetchone() is None:
                raise RuntimeError("empty probe result")
        except Exception as exc:
            error_code, safe_message = _safe_connection_error(exc)
            status = ConnectionStatus.ERROR
        else:
            error_code, safe_message = None, "连接成功"
            status = ConnectionStatus.HEALTHY
        finally:
            if connection is not None:
                connection.close()
        self._store.update_source(source.model_copy(update={
            "connection_status": status,
            "safe_probe_message": safe_message,
            "last_probed_at": checked_at,
            "updated_at": checked_at,
        }))
        return DataSourceConnectionProbe(
            status=status,
            error_code=error_code,
            safe_message=safe_message,
            checked_at=checked_at,
        )

    def probe_cdc(self, source_id: str) -> OutpatientCdcProbe:
        source = self._store.get_source(source_id)
        try:
            password = self._password(source)
            result = SqlServerOutpatientCdcSource(
                lambda: self._connection_factory(source, password)
            ).probe_cdc()
        except Exception:
            result = OutpatientCdcProbe(
                status="invalid",
                database_enabled=False,
                ready_captures=(),
                missing_captures=(),
                retention_minutes=None,
                safe_message="CDC 状态检查失败",
                checked_at=datetime.now(timezone.utc),
            )
        self._store.update_source(source.model_copy(update={
            "cdc_status": CdcEnablementStatus(result.status),
            "safe_probe_message": result.safe_message,
            "last_probed_at": result.checked_at,
            "updated_at": result.checked_at,
        }))
        return result

    def mark_waiting_dba(self, source_id: str, actor: str) -> None:
        del actor
        source = self._store.get_source(source_id)
        if source.cdc_status is CdcEnablementStatus.READY:
            return
        now = datetime.now(timezone.utc)
        self._store.update_source(source.model_copy(update={
            "cdc_status": CdcEnablementStatus.WAITING_DBA,
            "safe_probe_message": "等待医院 DBA 执行受控 CDC 脚本",
            "updated_at": now,
        }))

    def get_job(self, source_id: str) -> OutpatientSyncJob:
        return self._store.get_job(source_id)

    def save_job_config(self, source_id: str, request, actor: str) -> OutpatientSyncJob:
        del actor
        from src.adapters.insurance_interface.outpatient_source import OutpatientSourceMode
        self._store.get_source(source_id)
        now = datetime.now(timezone.utc)
        mode = OutpatientSourceMode(request.source_mode)
        try:
            current = self._store.get_job(source_id)
        except OutpatientGovernanceNotFoundError:
            if request.expected_revision != 1:
                raise SyncJobInvalidStateError("首次保存同步任务时修订号必须为 1")
            job = OutpatientSyncJob(
                source_id=source_id,
                source_mode=mode,
                status=SyncJobStatus.DRAFT,
                cdc_poll_interval_seconds=request.cdc_poll_interval_seconds,
                schedule_interval_minutes=request.schedule_interval_minutes,
                lookback_hours=request.lookback_hours,
                reconcile_time=request.reconcile_time,
                reconcile_days=request.reconcile_days,
                revision=1,
                created_at=now,
                updated_at=now,
            )
            self._store.save_job(job)
            return job
        mode_changed = current.source_mode != mode
        if mode_changed and (
            current.status not in {SyncJobStatus.DRAFT, SyncJobStatus.PAUSED}
            or not request.confirm_mode_switch
        ):
            raise SyncJobInvalidStateError("切换同步模式需先暂停任务并明确确认")
        job = current.model_copy(update={
            "source_mode": mode,
            "cdc_poll_interval_seconds": request.cdc_poll_interval_seconds,
            "schedule_interval_minutes": request.schedule_interval_minutes,
            "lookback_hours": request.lookback_hours,
            "reconcile_time": request.reconcile_time,
            "reconcile_days": request.reconcile_days,
            "revision": current.revision + 1,
            "baseline_required": current.baseline_required or mode_changed,
            "updated_at": now,
        })
        self._store.save_job(job, expected_revision=request.expected_revision)
        return job

    def start_job(self, source_id: str, actor: str) -> OutpatientSyncJob:
        del actor
        job = self._store.get_job(source_id)
        source = self._with_credential_status(self._store.get_source(source_id))
        if not source.credential_configured:
            raise SyncJobInvalidStateError("数据源凭据需重新提交")
        if job.source_mode.value == "cdc" and source.cdc_status is not CdcEnablementStatus.READY:
            raise CdcNotReadyError("CDC 尚未按受控模板开通")
        now = datetime.now(timezone.utc)
        return self._save_job_state(job, SyncJobStatus.READY, now, next_run_at=now)

    def pause_job(self, source_id: str, actor: str) -> OutpatientSyncJob:
        del actor
        job = self._store.get_job(source_id)
        return self._save_job_state(job, SyncJobStatus.PAUSED, datetime.now(timezone.utc))

    def request_run_once(self, source_id: str, actor: str) -> OutpatientSyncJob:
        del actor
        job = self._store.get_job(source_id)
        if job.status not in {SyncJobStatus.READY, SyncJobStatus.RUNNING}:
            raise SyncJobInvalidStateError("只有已启用任务可以请求立即执行")
        now = datetime.now(timezone.utc)
        updated = job.model_copy(update={
            "run_once_requested_at": now,
            "revision": job.revision + 1,
            "updated_at": now,
        })
        self._store.save_job(updated, expected_revision=job.revision)
        return updated

    def list_runs(self, source_id: str):
        self._store.get_source(source_id)
        return self._store.list_attempts(source_id)

    def postgres_target_status(self) -> PostgresTargetStatus:
        checked_at = datetime.now(timezone.utc)
        try:
            self._outpatient_store.ensure_schema()
            ready = self._outpatient_store.check_schema()
        except Exception:
            return PostgresTargetStatus(
                connection_status=ConnectionStatus.ERROR,
                schema_ready=False,
                safe_message="PostgreSQL 目标库连接失败",
                checked_at=checked_at,
            )
        return PostgresTargetStatus(
            connection_status=ConnectionStatus.HEALTHY,
            schema_ready=ready,
            safe_message="PostgreSQL 目标库已就绪" if ready else "PostgreSQL 目标表尚未就绪",
            checked_at=checked_at,
        )

    def open_source_connection(self, source_id: str):
        source = self._store.get_source(source_id)
        return self._connection_factory(source, self._password(source))

    @staticmethod
    def cdc_script_path() -> Path:
        return Path(__file__).resolve().parents[3] / "scripts" / "enable_outpatient_cdc.sql"

    def _password(self, source: OutpatientDataSource) -> str:
        credential = self._store.get_credential(source.credential_id)
        return self._vault.reveal(
            credential,
            endpoint=data_source_endpoint(
                source.host, source.port, source.database, source.username
            ),
        )

    def _with_credential_status(self, source: OutpatientDataSource) -> OutpatientDataSource:
        try:
            credential = self._store.get_credential(source.credential_id)
        except OutpatientGovernanceNotFoundError:
            configured = False
        else:
            configured = self._vault.is_bound(
                credential,
                endpoint=data_source_endpoint(
                    source.host, source.port, source.database, source.username
                ),
            )
        return source.model_copy(update={
            "credential_configured": configured,
            "credential_revision": credential.revision if configured else None,
        })

    def _save_job_state(
        self,
        job: OutpatientSyncJob,
        status: SyncJobStatus,
        now: datetime,
        *,
        next_run_at: datetime | None = None,
    ) -> OutpatientSyncJob:
        updated = job.model_copy(update={
            "status": status,
            "next_run_at": next_run_at if next_run_at is not None else job.next_run_at,
            "revision": job.revision + 1,
            "updated_at": now,
        })
        self._store.save_job(updated, expected_revision=job.revision)
        return updated


def _safe_connection_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, SourceContractMismatchError):
        return "source_contract_mismatch", "源表结构不符合门诊数据契约"
    if isinstance(exc, TimeoutError):
        return "timeout", "连接超时"
    message = str(exc).lower()
    if any(marker in message for marker in ("login failed", "authentication", "28000", "18456")):
        return "authentication_failed", "账号或密码验证失败"
    return "connection_failed", "连接失败"


def _source_issues(source, job, quality_status):
    from src.runtime.api.data_governance_schemas import DataGovernanceIssue

    issues = []
    if not source.credential_configured:
        issues.append(DataGovernanceIssue(
            code="credential_unavailable",
            severity="blocking",
            message="数据源凭据未配置或端点已变更",
            source_id=source.source_id,
        ))
    if source.connection_status is ConnectionStatus.ERROR:
        issues.append(DataGovernanceIssue(
            code="connection_error",
            severity="blocking",
            message="数据源连接异常",
            source_id=source.source_id,
        ))
    if job and job.status in {SyncJobStatus.DEGRADED, SyncJobStatus.FAILED}:
        issues.append(DataGovernanceIssue(
            code="sync_job_error",
            severity="blocking",
            message="同步任务需要处理",
            source_id=source.source_id,
        ))
    if quality_status == "blocked":
        issues.append(DataGovernanceIssue(
            code="quality_blocked",
            severity="blocking",
            message="最近批次未通过数据质量校验",
            source_id=source.source_id,
        ))
    return issues
