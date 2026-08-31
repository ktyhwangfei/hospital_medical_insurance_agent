from datetime import datetime, timezone

from cryptography.fernet import Fernet

from src.data_platform.outpatient_governance import ConnectionStatus
from src.runtime.data_governance.service import (
    CreateDataSourceCommand,
    DataGovernanceService,
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


class _PostgresStore:
    def ensure_schema(self):
        return None

    def check_schema(self):
        return True


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
