"""使用当前环境幂等配置门诊数据治理控制面。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_platform.outpatient_governance import (
    CdcEnablementStatus,
    ConnectionStatus,
    SyncJobStatus,
)
from src.data_platform.storage.postgresql.outpatient_governance_store import (
    OutpatientGovernanceNotFoundError,
    OutpatientGovernanceStore,
)
from src.data_platform.storage.postgresql.outpatient_store import OutpatientPostgresStore
from src.runtime.api.data_governance_schemas import (
    SaveSyncJobRequest,
    UpdateDataSourceRequest,
)
from src.runtime.data_governance.service import (
    CreateDataSourceCommand,
    DataGovernanceService,
)
from src.runtime.discovery.sqlserver_source import _try_connect


class BootstrapReadinessError(RuntimeError):
    """自动配置不能满足门诊唯一就绪条件。"""


class BootstrapResult(BaseModel):
    source_id: str
    platform_ready: bool
    source_status: ConnectionStatus
    postgresql_ready: bool
    cdc_status: CdcEnablementStatus
    source_mode: str
    job_status: SyncJobStatus


def command_from_environment() -> CreateDataSourceCommand:
    required = ("MSSQL_HOST", "MSSQL_DATABASE", "MSSQL_USER", "MSSQL_PASSWORD")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise BootstrapReadinessError("缺少当前测试环境配置：" + ", ".join(missing))
    source_id = os.getenv("OUTPATIENT_SOURCE_ID", "bjybdb")
    return CreateDataSourceCommand(
        source_id=source_id,
        hospital_code=os.getenv("OUTPATIENT_HOSPITAL_CODE", "TEST001"),
        hospital_name=os.getenv("OUTPATIENT_HOSPITAL_NAME", "测试医院门诊"),
        name=os.getenv("OUTPATIENT_SOURCE_NAME", "门诊医保库"),
        host=os.environ["MSSQL_HOST"],
        port=int(os.getenv("MSSQL_PORT", "1433")),
        database=os.environ["MSSQL_DATABASE"],
        schema_name="dbo",
        username=os.environ["MSSQL_USER"],
        credential_id=f"credential.{source_id}",
        password=os.environ["MSSQL_PASSWORD"],
    )


def bootstrap(service, command: CreateDataSourceCommand) -> BootstrapResult:
    actor = "local-environment-bootstrap"
    source = next(
        (item for item in service.list_sources() if item.source_id == command.source_id),
        None,
    )
    if source is None:
        source = service.create_source(command, actor)
    else:
        changes = {
            field: getattr(command, field)
            for field in (
                "hospital_code", "hospital_name", "name", "host", "port", "database", "username"
            )
            if getattr(source, field) != getattr(command, field)
        }
        endpoint_changed = bool({"host", "port", "database", "username"} & changes.keys())
        if changes:
            source = service.update_source_config(
                source.source_id,
                UpdateDataSourceRequest(**changes),
                actor,
            )
        if endpoint_changed or not source.credential_configured:
            if source.credential_revision is None:
                raise BootstrapReadinessError("现有数据源缺少可轮换的凭据版本")
            source = service.rotate_credential(
                source.source_id,
                source.credential_id,
                command.password.get_secret_value(),
                source.credential_revision,
                actor,
            )

    source_probe = service.probe_connection(source.source_id)
    if (
        source_probe.status is ConnectionStatus.ERROR
        and source_probe.error_code == "authentication_failed"
    ):
        source = service.rotate_credential(
            source.source_id,
            source.credential_id,
            command.password.get_secret_value(),
            source.credential_revision or 1,
            actor,
        )
        source_probe = service.probe_connection(source.source_id)
    if source_probe.status is not ConnectionStatus.HEALTHY:
        raise BootstrapReadinessError(source_probe.safe_message)

    postgresql = service.postgres_target_status()
    postgresql_ready = (
        postgresql.connection_status is ConnectionStatus.HEALTHY
        and postgresql.schema_ready
    )
    if not postgresql_ready:
        raise BootstrapReadinessError(postgresql.safe_message)

    cdc = service.probe_cdc(source.source_id)
    try:
        job = service.get_job(source.source_id)
    except OutpatientGovernanceNotFoundError:
        job = service.save_job_config(
            source.source_id,
            SaveSyncJobRequest(source_mode="scheduled_sql", expected_revision=1),
            actor,
        )
    return BootstrapResult(
        source_id=source.source_id,
        platform_ready=True,
        source_status=source_probe.status,
        postgresql_ready=True,
        cdc_status=CdcEnablementStatus(cdc.status),
        source_mode=job.source_mode.value,
        job_status=job.status,
    )


def main() -> int:
    def connect(source, password):
        connection, _driver = _try_connect({
            "host": source.host,
            "port": source.port,
            "database": source.database,
            "user": source.username,
            "password": password,
        })
        return connection

    try:
        result = bootstrap(
            DataGovernanceService(
                OutpatientGovernanceStore(),
                OutpatientPostgresStore(),
                connect,
            ),
            command_from_environment(),
        )
    except BootstrapReadinessError as exc:
        print(f"outpatient_governance_ready=false message={exc}", file=sys.stderr)
        return 1
    print(result.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
