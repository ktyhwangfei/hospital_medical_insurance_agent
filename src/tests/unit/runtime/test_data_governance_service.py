from datetime import datetime, timezone
from types import SimpleNamespace

from cryptography.fernet import Fernet
import pytest

from src.data_platform.outpatient_governance import ConnectionStatus, SyncJobStatus
from src.data_platform.storage.postgresql.outpatient_governance_store import (
    OutpatientGovernanceNotFoundError,
)
from src.runtime.api.data_governance_schemas import SaveSyncJobRequest, UpdateDataSourceRequest
from src.runtime.data_governance.service import (
    CreateDataSourceCommand,
    DataGovernanceService,
    SyncJobInvalidStateError,
)


class _GovernanceStore:
    def __init__(self):
        self.sources = {}
        self.credentials = {}
        self.updates = []

    def create_source_with_credential(self, source, credential):
        self.sources[source.source_id] = source
        self.credentials[credential.credential_id] = credential

    def get_source(self, source_id):
        return self.sources[source_id]

    def get_credential(self, credential_id):
        return self.credentials[credential_id]

    def update_source(self, source):
        self.sources[source.source_id] = source
        self.updates.append(source)

    def list_sources(self):
        return list(self.sources.values())

    def get_job(self, source_id):
        if not hasattr(self, "jobs") or source_id not in self.jobs:
            raise OutpatientGovernanceNotFoundError(source_id)
        return self.jobs[source_id]

    def save_job(self, job, expected_revision=None):
        del expected_revision
        if not hasattr(self, "jobs"):
            self.jobs = {}
        self.jobs[job.source_id] = job

    def list_attempts(self, source_id, limit=100):
        del source_id, limit
        return []


class _PostgresStore:
    def __init__(self, writable=True):
        self.writable = writable

    def ensure_schema(self):
        return None

    def check_schema(self):
        return True

    def check_writable(self):
        return self.writable

    def get_sync_status(self, source_id):
        return SimpleNamespace(
            source_id=source_id,
            last_non_empty_latency_seconds=None,
            quality_status=None,
        )


class _Connection:
    def __init__(self):
        self.closed = False
        self.executions = []

    def cursor(self):
        return self

    def execute(self, sql):
        self.executions.append(sql)

    def fetchone(self):
        return (1,)

    def close(self):
        self.closed = True


def _command(password="secret-value"):
    return CreateDataSourceCommand(
        source_id="bjybdb",
        hospital_code="H001",
        hospital_name="示例医院",
        name="门诊医保库",
        host="db.example",
        port=1433,
        database="bjybdb",
        schema_name="dbo",
        username="readonly",
        credential_id="credential.bjybdb",
        password=password,
    )


def test_create_source_seals_password_and_returns_public_model(monkeypatch) -> None:
    monkeypatch.setenv("DATA_GOVERNANCE_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    store = _GovernanceStore()
    service = DataGovernanceService(store, _PostgresStore(), lambda _source, _password: _Connection())

    source = service.create_source(_command(), actor="admin-1")

    assert "secret-value" not in source.model_dump_json()
    assert "encrypted_password" not in source.model_dump_json()
    assert "secret-value" not in store.credentials[source.credential_id].model_dump_json()


def test_endpoint_change_keeps_revision_available_for_credential_rebinding(monkeypatch) -> None:
    monkeypatch.setenv("DATA_GOVERNANCE_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    store = _GovernanceStore()
    service = DataGovernanceService(store, _PostgresStore(), lambda _source, _password: _Connection())
    service.create_source(_command(), actor="admin-1")

    source = service.update_source_config(
        "bjybdb", UpdateDataSourceRequest(host="replacement.example"), actor="admin-1"
    )

    assert source.credential_configured is False
    assert source.credential_revision == 1


def test_connection_probe_returns_only_safe_error_code(monkeypatch) -> None:
    monkeypatch.setenv("DATA_GOVERNANCE_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    store = _GovernanceStore()
    service = DataGovernanceService(
        store,
        _PostgresStore(),
        lambda _source, _password: (_ for _ in ()).throw(
            RuntimeError("Login failed for password=secret-value at db.example")
        ),
    )
    service.create_source(_command(), actor="admin-1")

    result = service.probe_connection("bjybdb")

    assert result.status is ConnectionStatus.ERROR
    assert result.error_code == "authentication_failed"
    output = result.model_dump_json()
    assert "secret-value" not in output
    assert "db.example" not in output
    assert store.updates[-1].connection_status is ConnectionStatus.ERROR


def test_connection_probe_identifies_credentials_encrypted_with_an_old_key(monkeypatch) -> None:
    monkeypatch.setenv("DATA_GOVERNANCE_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    store = _GovernanceStore()
    DataGovernanceService(
        store, _PostgresStore(), lambda _source, _password: _Connection()
    ).create_source(_command(), actor="admin-1")
    monkeypatch.setenv("DATA_GOVERNANCE_MASTER_KEY", Fernet.generate_key().decode("ascii"))

    result = DataGovernanceService(
        store, _PostgresStore(), lambda _source, _password: _Connection()
    ).probe_connection("bjybdb")

    assert result.status is ConnectionStatus.ERROR
    assert result.error_code == "credential_unavailable"
    assert result.safe_message == "数据源凭据需重新提交"


def test_connection_probe_closes_successful_connection(monkeypatch) -> None:
    monkeypatch.setenv("DATA_GOVERNANCE_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    store = _GovernanceStore()
    connection = _Connection()
    service = DataGovernanceService(store, _PostgresStore(), lambda _s, _p: connection)
    service.create_source(_command(), actor="admin-1")

    result = service.probe_connection("bjybdb")

    assert result.status is ConnectionStatus.HEALTHY
    assert result.safe_message == "门诊 3 张源表及 117 个契约字段可读"
    assert len(connection.executions) == 3
    assert result.checked_at <= datetime.now(timezone.utc)
    assert connection.closed is True


def test_overview_is_ready_without_cdc_when_source_and_postgres_are_ready(monkeypatch) -> None:
    monkeypatch.setenv("DATA_GOVERNANCE_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    store = _GovernanceStore()
    service = DataGovernanceService(store, _PostgresStore(), lambda _s, _p: _Connection())
    service.create_source(_command(), actor="admin-1")
    service.probe_connection("bjybdb")

    overview = service.overview()

    assert overview.platform_ready is True
    assert overview.postgresql.connection_status is ConnectionStatus.HEALTHY
    assert overview.postgresql.schema_ready is True


def test_scheduled_sql_start_requires_source_and_postgres_but_not_cdc(monkeypatch) -> None:
    monkeypatch.setenv("DATA_GOVERNANCE_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    store = _GovernanceStore()
    postgres = _PostgresStore()
    service = DataGovernanceService(store, postgres, lambda _s, _p: _Connection())
    service.create_source(_command(), actor="admin-1")
    service.save_job_config("bjybdb", SaveSyncJobRequest(
        source_mode="scheduled_sql", expected_revision=1,
    ), actor="admin-1")

    with pytest.raises(SyncJobInvalidStateError, match="门诊源表"):
        service.start_job("bjybdb", actor="admin-1")

    service.probe_connection("bjybdb")
    postgres.writable = False
    with pytest.raises(SyncJobInvalidStateError, match="PostgreSQL"):
        service.start_job("bjybdb", actor="admin-1")

    postgres.writable = True
    started = service.start_job("bjybdb", actor="admin-1")
    assert started.status is SyncJobStatus.READY


def test_start_job_clears_stale_active_attempt(monkeypatch) -> None:
    """worker 崩溃残留 active_attempt_id 时，手动重启必须清掉，否则任务永远无法再被认领。"""
    monkeypatch.setenv("DATA_GOVERNANCE_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    store = _GovernanceStore()
    service = DataGovernanceService(store, _PostgresStore(), lambda _s, _p: _Connection())
    service.create_source(_command(), actor="admin-1")
    service.save_job_config("bjybdb", SaveSyncJobRequest(
        source_mode="scheduled_sql", expected_revision=1,
    ), actor="admin-1")
    service.probe_connection("bjybdb")
    store.jobs["bjybdb"] = store.jobs["bjybdb"].model_copy(
        update={"active_attempt_id": "stale-attempt", "status": SyncJobStatus.RUNNING}
    )

    started = service.start_job("bjybdb", actor="admin-1")

    assert started.status is SyncJobStatus.READY
    assert started.active_attempt_id is None


def test_cdc_waiting_state_does_not_overwrite_source_readiness_message(monkeypatch) -> None:
    monkeypatch.setenv("DATA_GOVERNANCE_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    store = _GovernanceStore()
    service = DataGovernanceService(store, _PostgresStore(), lambda _s, _p: _Connection())
    service.create_source(_command(), actor="admin-1")
    service.probe_connection("bjybdb")

    service.mark_waiting_dba("bjybdb", actor="admin-1")

    source = store.get_source("bjybdb")
    assert source.safe_probe_message == "门诊 3 张源表及 117 个契约字段可读"
