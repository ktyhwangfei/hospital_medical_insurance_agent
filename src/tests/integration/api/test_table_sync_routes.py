"""选表同步 API 测试：/data-governance/data-sources/{id}/sync-tables。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.data_platform.table_sync import SelectedSyncTable, TableSyncRunResult
from src.runtime.api.app import create_app
from src.runtime.api.data_governance_routes import get_table_sync_executor

PREFIX = "/api/v1/medical-insurance-ai-agent/data-governance/data-sources/bjybdb/sync-tables"
JWT_SECRET = "table-sync-test-secret"


def _token(permissions):
    h = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    p = base64.urlsafe_b64encode(json.dumps({
        "sub": "admin-1", "roles": ["system_admin"], "permissions": permissions,
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }).encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(
        hmac.new(JWT_SECRET.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return f"Bearer {h}.{p}.{sig}"


READ = {"Authorization": _token(["data_governance:read"])}
WRITE = {"Authorization": _token(["data_governance:write"])}


class _FakeStore:
    def __init__(self):
        self.tables: dict[str, SelectedSyncTable] = {}

    def save_table(self, table):
        self.tables[table.table_name] = table
        return table

    def list_tables(self, source_id):
        return list(self.tables.values())

    def remove_table(self, source_id, table_name):
        self.tables.pop(table_name, None)

    def record_event(self, source_id, table_name, action, actor, row_count=None):
        pass


class _FakeExecutor:
    def __init__(self):
        self._store = _FakeStore()

    def probe_table_keys(self, source_id, table_name):
        return ["djh"]

    def sync_all_active(self, source_id, *, manual=False):
        return [
            TableSyncRunResult(
                table_name=t.table_name, target_table=t.target_table,
                row_count=33, duration_ms=100,
            )
            for t in self._store.tables.values()
        ]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    app = create_app()
    executor = _FakeExecutor()
    app.dependency_overrides[get_table_sync_executor] = lambda: executor
    return TestClient(app), executor


def test_select_list_run_remove_flow(client):
    http, executor = client

    res = http.put(f"{PREFIX}/yb_mzjyxx", json={}, headers=WRITE)
    assert res.status_code == 201, res.text
    body = res.json()["result"]
    assert body["target_table"] == "yb_mzjyxx"
    assert body["key_columns"] == ["djh"]  # 自动探查主键
    assert body["status"] == "active"

    res = http.get(PREFIX, headers=READ)
    assert [t["table_name"] for t in res.json()["result"]] == ["yb_mzjyxx"]

    res = http.post(f"{PREFIX}/run", headers=WRITE)
    assert res.status_code == 200
    assert res.json()["result"][0]["row_count"] == 33

    res = http.delete(f"{PREFIX}/yb_mzjyxx", headers=WRITE)
    assert res.status_code == 200
    assert http.get(PREFIX, headers=READ).json()["result"] == []


def test_requires_auth(client):
    http, _ = client
    assert http.get(PREFIX).status_code == 401
    assert http.put(f"{PREFIX}/yb_mzjyxx", json={}).status_code == 401
