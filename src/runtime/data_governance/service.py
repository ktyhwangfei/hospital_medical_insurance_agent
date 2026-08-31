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
    PostgresTargetStatus,
)
from src.security.data_source_credentials import (
    DataSourceCredentialVault,
    data_source_endpoint,
)


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


def _safe_connection_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, SourceContractMismatchError):
        return "source_contract_mismatch", "源表结构不符合门诊数据契约"
    if isinstance(exc, TimeoutError):
        return "timeout", "连接超时"
    message = str(exc).lower()
    if any(marker in message for marker in ("login failed", "authentication", "28000", "18456")):
        return "authentication_failed", "账号或密码验证失败"
    return "connection_failed", "连接失败"
