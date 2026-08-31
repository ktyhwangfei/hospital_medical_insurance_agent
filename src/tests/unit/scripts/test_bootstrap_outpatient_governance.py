from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts.bootstrap_outpatient_governance import (
    BootstrapReadinessError,
    bootstrap,
    command_from_environment,
)
from src.data_platform.outpatient_governance import (
    CdcEnablementStatus,
    ConnectionStatus,
    SyncJobStatus,
)
from src.data_platform.storage.postgresql.outpatient_governance_store import (
    OutpatientGovernanceNotFoundError,
)
from src.runtime.data_governance.service import CreateDataSourceCommand


NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)


class _Service:
    def __init__(self, *, postgres_ready=True):
        self.sources = {}
        self.jobs = {}
        self.create_count = 0
        self.save_job_count = 0
        self.postgres_ready = postgres_ready

    def list_sources(self):
        return list(self.sources.values())

    def create_source(self, command, actor):
        del actor
        self.create_count += 1
        source = SimpleNamespace(
            source_id=command.source_id,
            hospital_code=command.hospital_code,
            hospital_name=command.hospital_name,
            name=command.name,
            host=command.host,
            port=command.port,
            database=command.database,
            username=command.username,
            credential_id=command.credential_id,
            credential_configured=True,
            credential_revision=1,
            connection_status=ConnectionStatus.UNKNOWN,
            cdc_status=CdcEnablementStatus.NOT_CHECKED,
        )
        self.sources[source.source_id] = source
        return source

    def update_source_config(self, source_id, request, actor):
        del request, actor
        return self.sources[source_id]

    def rotate_credential(self, source_id, credential_id, password, expected_revision, actor):
        del credential_id, password, expected_revision, actor
        return self.sources[source_id]

    def probe_connection(self, source_id):
        self.sources[source_id].connection_status = ConnectionStatus.HEALTHY
        return SimpleNamespace(
            status=ConnectionStatus.HEALTHY,
            error_code=None,
            safe_message="门诊 3 张源表及 117 个契约字段可读",
        )

    def postgres_target_status(self):
        return SimpleNamespace(
            connection_status=(
                ConnectionStatus.HEALTHY if self.postgres_ready else ConnectionStatus.ERROR
            ),
            schema_ready=self.postgres_ready,
            safe_message=(
                "PostgreSQL 门诊结构及读写已就绪"
                if self.postgres_ready else "PostgreSQL 目标库连接失败"
            ),
        )

    def probe_cdc(self, source_id):
        self.sources[source_id].cdc_status = CdcEnablementStatus.WAITING_DBA
        return SimpleNamespace(status="waiting_dba", safe_message="数据库尚未开启 CDC")

    def get_job(self, source_id):
        if source_id not in self.jobs:
            raise OutpatientGovernanceNotFoundError(source_id)
        return self.jobs[source_id]

    def save_job_config(self, source_id, request, actor):
        del actor
        self.save_job_count += 1
        job = SimpleNamespace(
            source_id=source_id,
            source_mode=SimpleNamespace(value=request.source_mode),
            status=SyncJobStatus.DRAFT,
        )
        self.jobs[source_id] = job
        return job


class _StaleCredentialService(_Service):
    def __init__(self):
        super().__init__()
        source = self.create_source(_command(), "test")
        source.credential_configured = False
        source.credential_revision = 3
        self.rotate_expected_revision = None

    def rotate_credential(self, source_id, credential_id, password, expected_revision, actor):
        del credential_id, password, actor
        assert expected_revision == 3
        self.rotate_expected_revision = expected_revision
        self.sources[source_id].credential_configured = True
        self.sources[source_id].credential_revision = expected_revision + 1
        return self.sources[source_id]


class _OldMasterKeyService(_StaleCredentialService):
    def __init__(self):
        super().__init__()
        self.sources["bjybdb"].credential_configured = True
        self.rotated = False

    def probe_connection(self, source_id):
        if not self.rotated:
            return SimpleNamespace(
                status=ConnectionStatus.ERROR,
                error_code="credential_unavailable",
                safe_message="数据源凭据需重新提交",
            )
        return super().probe_connection(source_id)

    def rotate_credential(self, *args, **kwargs):
        source = super().rotate_credential(*args, **kwargs)
        self.rotated = True
        return source


def _command(password="never-print-this"):
    return CreateDataSourceCommand(
        source_id="bjybdb",
        hospital_code="TEST001",
        hospital_name="测试医院门诊",
        name="门诊医保库",
        host="127.0.0.1",
        port=1433,
        database="bjybdb",
        schema_name="dbo",
        username="sa",
        credential_id="credential.bjybdb",
        password=password,
    )


def test_bootstrap_is_idempotent_and_creates_one_scheduled_sql_draft() -> None:
    service = _Service()

    first = bootstrap(service, _command())
    second = bootstrap(service, _command())

    assert service.create_count == 1
    assert service.save_job_count == 1
    assert first.platform_ready is True
    assert second.platform_ready is True
    assert second.source_status is ConnectionStatus.HEALTHY
    assert second.postgresql_ready is True
    assert second.cdc_status is CdcEnablementStatus.WAITING_DBA
    assert second.job_status is SyncJobStatus.DRAFT
    assert second.source_mode == "scheduled_sql"
    assert "never-print-this" not in second.model_dump_json()


def test_bootstrap_rebinds_an_existing_unconfigured_credential() -> None:
    service = _StaleCredentialService()

    result = bootstrap(service, _command())

    assert result.platform_ready is True
    assert service.rotate_expected_revision == 3


def test_bootstrap_reseals_a_credential_after_master_key_rotation() -> None:
    service = _OldMasterKeyService()

    result = bootstrap(service, _command())

    assert result.platform_ready is True
    assert service.rotated is True


def test_bootstrap_fails_closed_when_postgresql_is_not_writable() -> None:
    service = _Service(postgres_ready=False)

    with pytest.raises(BootstrapReadinessError, match="PostgreSQL"):
        bootstrap(service, _command())

    assert service.save_job_count == 0


def test_command_from_environment_requires_existing_sqlserver_credentials(monkeypatch) -> None:
    for name in ("MSSQL_HOST", "MSSQL_DATABASE", "MSSQL_USER", "MSSQL_PASSWORD"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(BootstrapReadinessError, match="MSSQL_HOST"):
        command_from_environment()


def test_command_from_environment_uses_current_test_configuration(monkeypatch) -> None:
    values = {
        "MSSQL_HOST": "127.0.0.1", "MSSQL_PORT": "1433",
        "MSSQL_DATABASE": "bjybdb", "MSSQL_USER": "sa",
        "MSSQL_PASSWORD": "never-print-this",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    command = command_from_environment()

    assert command.source_id == "bjybdb"
    assert command.database == "bjybdb"
    assert command.password.get_secret_value() == "never-print-this"
