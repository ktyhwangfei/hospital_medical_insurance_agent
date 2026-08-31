from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.adapters.insurance_interface.outpatient_cdc import OutpatientCdcProbe
from src.adapters.insurance_interface.outpatient_source import OutpatientSourceMode
from src.data_platform.outpatient_governance import (
    CdcEnablementStatus,
    ConnectionStatus,
    OutpatientDataSource,
    OutpatientSyncAttempt,
    OutpatientSyncJob,
    PostgresTargetStatus,
    SyncJobStatus,
)
from src.runtime.api.app import create_app
from src.runtime.api.data_governance_routes import get_data_governance_service
from src.runtime.api.data_governance_schemas import (
    DataGovernanceOverview,
    DataGovernanceSourceStatus,
)


PREFIX = "/api/v1/medical-insurance-ai-agent/data-governance"
JWT_SECRET = "data-governance-test-secret"
NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)


def _token(permissions):
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": "admin-1",
        "roles": ["system_admin"],
        "permissions": permissions,
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    encoded_header = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    encoded_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = base64.urlsafe_b64encode(hmac.new(
        JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256
    ).digest()).decode().rstrip("=")
    return f"Bearer {signing_input}.{signature}"


def _headers(permission):
    return {"Authorization": _token([permission])}


def _source():
    return OutpatientDataSource(
        source_id="bjybdb",
        hospital_code="H001",
        hospital_name="示例医院",
        name="门诊医保库",
        host="db.example",
        database="bjybdb",
        username="readonly",
        credential_id="credential.bjybdb",
        connection_status=ConnectionStatus.HEALTHY,
        cdc_status=CdcEnablementStatus.WAITING_DBA,
        safe_probe_message="门诊 3 张源表及 117 个契约字段可读",
        created_at=NOW,
        updated_at=NOW,
    )


def _job():
    return OutpatientSyncJob(
        source_id="bjybdb",
        source_mode=OutpatientSourceMode.CDC,
        status=SyncJobStatus.PAUSED,
        reconcile_time=time(2),
        created_at=NOW,
        updated_at=NOW,
    )


def _payload(password="password-never-returned"):
    return {
        "source_id": "bjybdb",
        "hospital_code": "H001",
        "hospital_name": "示例医院",
        "name": "门诊医保库",
        "host": "db.example",
        "port": 1433,
        "database": "bjybdb",
        "schema_name": "dbo",
        "username": "readonly",
        "credential": {
            "credential_id": "credential.bjybdb",
            "password": password,
        },
    }


class _Service:
    def __init__(self, script_path):
        self.source = _source()
        self.job = _job()
        self.script_path = script_path
        self.calls = []

    def overview(self):
        return DataGovernanceOverview(
            platform_ready=True,
            postgresql=self.postgres_target_status(),
            data_source_count=1,
            running_job_count=0,
            issue_count=0,
            latest_latency_seconds=42,
            sources=[DataGovernanceSourceStatus.from_source(self.source, self.job)],
            issues=[],
            recent_runs=[],
        )

    def list_sources(self):
        return [self.source]

    def create_source(self, command, actor):
        self.calls.append(("create", actor, command.password.get_secret_value()))
        return self.source

    def update_source_config(self, source_id, request, actor):
        self.calls.append(("update", source_id, actor))
        return self.source

    def rotate_credential(self, source_id, credential_id, password, expected_revision, actor):
        self.calls.append(("rotate", source_id, actor, password))
        return self.source

    def probe_connection(self, source_id):
        return SimpleNamespace(
            status=ConnectionStatus.HEALTHY,
            error_code=None,
            safe_message="门诊 3 张源表及 117 个契约字段可读",
            checked_at=NOW,
        )

    def cdc_script_path(self):
        return self.script_path

    def mark_waiting_dba(self, source_id, actor):
        self.calls.append(("waiting_dba", source_id, actor))

    def probe_cdc(self, source_id):
        return OutpatientCdcProbe(
            status="ready",
            database_enabled=True,
            ready_captures=("dbo_o_Trade", "dbo_o_FeeItem", "dbo_o_Diagnose"),
            missing_captures=(),
            retention_minutes=4320,
            safe_message="CDC 已按受控模板开通",
            checked_at=NOW,
        )

    def postgres_target_status(self):
        return PostgresTargetStatus(
            connection_status=ConnectionStatus.HEALTHY,
            schema_ready=True,
            safe_message="PostgreSQL 门诊结构及读写已就绪",
            checked_at=NOW,
        )

    def get_job(self, source_id):
        return self.job

    def save_job_config(self, source_id, request, actor):
        self.calls.append(("save_job", source_id, actor))
        return self.job

    def start_job(self, source_id, actor):
        self.calls.append(("start", source_id, actor))
        return self.job.model_copy(update={"status": SyncJobStatus.READY})

    def pause_job(self, source_id, actor):
        self.calls.append(("pause", source_id, actor))
        return self.job

    def request_run_once(self, source_id, actor):
        self.calls.append(("run_once", source_id, actor))
        return self.job

    def list_runs(self, source_id):
        return [OutpatientSyncAttempt(
            attempt_id="attempt-1",
            source_id=source_id,
            source_mode=OutpatientSourceMode.CDC,
            run_kind="incremental",
            status="succeeded",
            started_at=NOW,
            finished_at=NOW,
            row_count=3,
            batch_id="batch-1",
        )]


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    script = tmp_path / "enable_outpatient_cdc.sql"
    script.write_text("SELECT 1;", encoding="utf-8")
    service = _Service(script)
    app = create_app()
    app.dependency_overrides[get_data_governance_service] = lambda: service
    return TestClient(app), service


def test_data_governance_requires_signed_token(client):
    response = client[0].get(f"{PREFIX}/overview")
    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "AUTH_REQUIRED"


def test_read_permission_cannot_create_datasource(client):
    response = client[0].post(
        f"{PREFIX}/data-sources",
        headers=_headers("data_governance:read"),
        json=_payload(),
    )
    assert response.status_code == 403


def test_create_datasource_never_echoes_password(client):
    response = client[0].post(
        f"{PREFIX}/data-sources",
        headers=_headers("data_governance:write"),
        json=_payload(),
    )
    assert response.status_code == 201
    assert "password-never-returned" not in response.text
    assert response.json()["result"]["credential_configured"] is True


@pytest.mark.parametrize("path", [
    "/overview",
    "/data-sources",
    "/postgresql/status",
    "/sync-jobs/bjybdb",
    "/sync-jobs/bjybdb/runs",
])
def test_read_endpoints_are_available(client, path):
    response = client[0].get(
        PREFIX + path,
        headers=_headers("data_governance:read"),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_overview_reports_platform_ready_independently_from_cdc(client):
    response = client[0].get(
        f"{PREFIX}/overview",
        headers=_headers("data_governance:read"),
    )

    result = response.json()["result"]
    assert result["platform_ready"] is True
    assert result["postgresql"]["connection_status"] == "healthy"
    assert result["postgresql"]["schema_ready"] is True
    assert result["postgresql"]["safe_message"] == "PostgreSQL 门诊结构及读写已就绪"
    assert result["sources"][0]["cdc_status"] == "waiting_dba"


def test_all_write_actions_and_cdc_download_are_controlled(client):
    api, service = client
    headers = _headers("data_governance:write")
    actions = [
        api.patch(f"{PREFIX}/data-sources/bjybdb", headers=headers, json={"name": "新名称"}),
        api.put(f"{PREFIX}/data-sources/bjybdb/credential", headers=headers, json={
            "credential_id": "credential.bjybdb", "password": "new-never-returned",
            "expected_revision": 1,
        }),
        api.post(f"{PREFIX}/data-sources/bjybdb/test", headers=headers),
        api.post(f"{PREFIX}/data-sources/bjybdb/cdc-check", headers=headers),
        api.put(f"{PREFIX}/sync-jobs/bjybdb", headers=headers, json={
            "source_mode": "cdc", "expected_revision": 1,
        }),
        api.post(f"{PREFIX}/sync-jobs/bjybdb/start", headers=headers),
        api.post(f"{PREFIX}/sync-jobs/bjybdb/pause", headers=headers),
        api.post(f"{PREFIX}/sync-jobs/bjybdb/run-once", headers=headers),
    ]
    assert [response.status_code for response in actions] == [200] * len(actions)
    assert all("never-returned" not in response.text for response in actions)
    assert ("run_once", "bjybdb", "admin-1") in service.calls

    download = api.get(f"{PREFIX}/data-sources/bjybdb/cdc-script", headers=headers)
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/sql")
    assert ("waiting_dba", "bjybdb", "admin-1") in service.calls


def test_database_error_is_sanitized(client):
    def fail():
        raise RuntimeError("postgresql://user:secret@db/internal")

    client[1].overview = fail
    response = client[0].get(
        f"{PREFIX}/overview",
        headers=_headers("data_governance:read"),
    )
    assert response.status_code == 503
    assert "secret" not in response.text
    assert response.json()["detail"]["error_code"] == "DATA_GOVERNANCE_UNAVAILABLE"
