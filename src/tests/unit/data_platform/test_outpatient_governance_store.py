from contextlib import contextmanager
from datetime import datetime, time, timezone

from cryptography.fernet import Fernet
import pytest

from src.adapters.insurance_interface.outpatient_source import OutpatientSourceMode
from src.data_platform.outpatient_governance import (
    ConnectionStatus,
    CdcEnablementStatus,
    OutpatientDataSource,
    OutpatientSyncJob,
    SyncJobStatus,
)
from src.data_platform.storage.postgresql.outpatient_governance_store import (
    OutpatientGovernanceConflictError,
    OutpatientGovernanceStore,
)
from src.security.data_source_credentials import DataSourceCredentialVault


NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, client):
        self.client = client
        self.row = None
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        self.client.transaction_sql.append((sql, params))
        if "SELECT revision" in sql:
            self.row = (self.client.credential_revision,)
        return self

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, client):
        self.client = client

    def cursor(self):
        return _Cursor(self.client)


class _Client:
    def __init__(self):
        self.schema_sql = []
        self.transaction_sql = []
        self.transaction_count = 0
        self.credential_revision = 1
        self.source_rows = []
        self.update_rows = []

    def execute(self, sql, params=()):
        self.schema_sql.append((sql, params))
        if sql.lstrip().startswith("SELECT") and "outpatient_data_sources" in sql:
            return self.source_rows
        if "UPDATE outpatient_sync_jobs" in sql and "RETURNING" in sql:
            return self.update_rows
        return []

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        yield _Connection(self)


def _source() -> OutpatientDataSource:
    return OutpatientDataSource(
        source_id="bjybdb",
        hospital_code="H001",
        hospital_name="示例医院",
        name="门诊医保库",
        host="db.example",
        database="bjybdb",
        username="readonly",
        credential_id="credential.bjybdb",
        connection_status=ConnectionStatus.UNKNOWN,
        cdc_status=CdcEnablementStatus.NOT_CHECKED,
        created_at=NOW,
        updated_at=NOW,
    )


def _job() -> OutpatientSyncJob:
    return OutpatientSyncJob(
        source_id="bjybdb",
        source_mode=OutpatientSourceMode.CDC,
        status=SyncJobStatus.DRAFT,
        reconcile_time=time(2),
        created_at=NOW,
        updated_at=NOW,
    )


def test_schema_migrates_all_four_control_plane_tables() -> None:
    client = _Client()
    OutpatientGovernanceStore(client=client).ensure_schema()

    ddl = "\n".join(sql for sql, _params in client.schema_sql)
    for table in (
        "outpatient_data_sources",
        "outpatient_data_source_credentials",
        "outpatient_sync_jobs",
        "outpatient_sync_attempts",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in ddl
        assert f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS" in ddl


def test_create_source_and_credential_is_atomic_and_source_never_contains_ciphertext(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATA_GOVERNANCE_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    source = _source()
    credential = DataSourceCredentialVault().seal(
        credential_id=source.credential_id,
        password="secret-value",
        endpoint="sqlserver://db.example:1433/bjybdb/readonly",
        actor="admin-1",
        revision=1,
    )
    client = _Client()
    store = OutpatientGovernanceStore(client=client)

    store.create_source_with_credential(source, credential)

    assert client.transaction_count == 1
    sql = "\n".join(statement for statement, _params in client.transaction_sql)
    assert "INSERT INTO outpatient_data_sources" in sql
    assert "INSERT INTO outpatient_data_source_credentials" in sql
    assert "secret-value" not in source.model_dump_json()
    assert "encrypted_password" not in source.model_dump_json()


def test_job_defaults_match_approved_operating_parameters() -> None:
    job = _job()

    assert job.cdc_poll_interval_seconds == 45
    assert job.schedule_interval_minutes == 5
    assert job.lookback_hours == 2
    assert job.reconcile_days == 30
    assert job.baseline_required is True


def test_source_listing_only_reads_public_source_table() -> None:
    client = _Client()
    client.source_rows = [{
        **_source().model_dump(exclude={"database"}),
        "database_name": "bjybdb",
    }]
    store = OutpatientGovernanceStore(client=client)

    result = store.list_sources()

    assert result == [_source()]
    reads = [sql for sql, _params in client.schema_sql if sql.lstrip().startswith("SELECT")]
    assert all("outpatient_data_source_credentials" not in sql for sql in reads)


def test_rotate_credential_and_job_update_enforce_revision(monkeypatch) -> None:
    monkeypatch.setenv("DATA_GOVERNANCE_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    vault = DataSourceCredentialVault()
    credential = vault.seal(
        credential_id="credential.bjybdb",
        password="new-secret",
        endpoint="sqlserver://db.example:1433/bjybdb/readonly",
        actor="admin-1",
        revision=2,
    )
    client = _Client()
    store = OutpatientGovernanceStore(client=client)

    store.rotate_credential(credential, expected_revision=1)
    assert client.transaction_count == 1

    with pytest.raises(OutpatientGovernanceConflictError, match="版本冲突"):
        store.rotate_credential(credential, expected_revision=2)

    client.update_rows = [{"source_id": "bjybdb"}]
    updated_job = _job().model_copy(update={"revision": 2})
    store.save_job(updated_job, expected_revision=1)
    update_sql, params = next(
        item for item in client.schema_sql if "UPDATE outpatient_sync_jobs" in item[0]
    )
    assert update_sql.count("%s") == len(params)
