"""健康运营 /ops API 测试 — issue #45 P0（鉴权 + 巡检去重 + 列表过滤分页）
+ #50（详情 / ignore / reopen 状态机与乐观锁）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.adapters.insurance_interface.outpatient_source import OutpatientSourceMode
from src.data_platform.outpatient_governance import (
    CdcEnablementStatus,
    ConnectionStatus,
    OutpatientDataSource,
    OutpatientSyncJob,
    SyncJobStatus,
)
from src.data_platform.storage.postgresql.outpatient_governance_store import (
    OutpatientGovernanceNotFoundError,
)
from src.data_platform.storage.ops.ops_in_memory import InMemoryOpsFindingStorage
from src.runtime.api.app import create_app
from src.runtime.api.ops_routes import get_ops_service
from src.runtime.ops.service import OpsHealthService

BASE = "/api/v1/medical-insurance-ai-agent/ops"
JWT_SECRET = "ops-test-secret"
NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def _token(permissions):
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": "ops-admin-1",
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


def _source(status: ConnectionStatus = ConnectionStatus.HEALTHY) -> OutpatientDataSource:
    return OutpatientDataSource(
        source_id="bjybdb",
        hospital_code="H001",
        hospital_name="示例医院",
        name="门诊医保库",
        host="db.example",
        database="bjybdb",
        username="readonly",
        credential_id="credential.bjybdb",
        connection_status=status,
        cdc_status=CdcEnablementStatus.WAITING_DBA,
        safe_probe_message="探测失败：连接超时" if status is ConnectionStatus.ERROR else None,
        last_probed_at=NOW if status is ConnectionStatus.ERROR else None,
        created_at=NOW,
        updated_at=NOW,
    )


def _job(status: SyncJobStatus) -> OutpatientSyncJob:
    return OutpatientSyncJob(
        source_id="bjybdb",
        source_mode=OutpatientSourceMode.CDC,
        status=status,
        schedule_interval_minutes=5,
        next_run_at=NOW + timedelta(minutes=5),
        created_at=NOW,
        updated_at=NOW,
    )


class _BrokenReader:
    """检查器容错路径：读取面整体抛错。"""

    def list_sources(self):
        raise RuntimeError("治理控制面不可用")

    def get_job(self, source_id):
        raise OutpatientGovernanceNotFoundError(source_id)


class _Reader:
    def __init__(self, sources=(), jobs=None):
        self._sources = list(sources)
        self._jobs = jobs or {}

    def list_sources(self):
        return list(self._sources)

    def get_job(self, source_id):
        if source_id not in self._jobs:
            raise OutpatientGovernanceNotFoundError(source_id)
        return self._jobs[source_id]


@pytest.fixture
def api_factory(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)

    def build(reader) -> TestClient:
        # 依赖注入必须复用同一服务实例：lambda 内 new 存储会让每个请求拿到空库
        service = OpsHealthService(InMemoryOpsFindingStorage(), lambda: reader)
        app = create_app()
        app.dependency_overrides[get_ops_service] = lambda: service
        return TestClient(app, raise_server_exceptions=False)

    return build


class TestAuth:
    def test_missing_token_401(self, api_factory):
        api = api_factory(_Reader())
        assert api.post(f"{BASE}/inspections").status_code == 401
        assert api.get(f"{BASE}/findings").status_code == 401

    def test_wrong_permission_403(self, api_factory):
        api = api_factory(_Reader())
        assert api.post(f"{BASE}/inspections", headers=_headers("ops:read")).status_code == 403
        assert api.get(f"{BASE}/findings", headers=_headers("ops:write")).status_code == 403


class TestInspection:
    def test_healthy_state_zero_findings(self, api_factory):
        api = api_factory(_Reader([_source()], {"bjybdb": _job(SyncJobStatus.RUNNING)}))
        resp = api.post(f"{BASE}/inspections", headers=_headers("ops:write"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["check_count"] == 2
        assert body["finding_count"] == 0
        assert body["checker_errors"] == []

    def test_problems_upserted_and_deduped(self, api_factory):
        api = api_factory(_Reader(
            [_source(ConnectionStatus.ERROR)],
            {"bjybdb": _job(SyncJobStatus.FAILED)},
        ))
        first = api.post(f"{BASE}/inspections", headers=_headers("ops:write")).json()
        assert first["finding_count"] == 2
        second = api.post(f"{BASE}/inspections", headers=_headers("ops:write")).json()
        # fingerprint 去重：重复巡检 occurrence_count 累计而非新增行
        assert second["finding_count"] == 2
        listed = api.get(f"{BASE}/findings?status=open", headers=_headers("ops:read")).json()
        assert listed["total"] == 2
        assert all(item["occurrence_count"] == 2 for item in listed["items"])

    def test_checker_error_does_not_abort_inspection(self, api_factory):
        api = api_factory(_BrokenReader())
        resp = api.post(f"{BASE}/inspections", headers=_headers("ops:write"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["finding_count"] == 0
        assert {err["check_id"] for err in body["checker_errors"]} == {
            "data_sync_failed", "data_source_down",
        }


class TestFindingsList:
    @pytest.fixture
    def api(self, api_factory):
        # 同步任务 DEGRADED（warning）+ 连接探测失败（critical），两条不同严重度
        reader = _Reader(
            [_source(ConnectionStatus.ERROR)],
            {"bjybdb": _job(SyncJobStatus.DEGRADED)},
        )
        api = api_factory(reader)
        api.post(f"{BASE}/inspections", headers=_headers("ops:write"))
        return api

    def test_severity_filter(self, api):
        body = api.get(
            f"{BASE}/findings?severity=critical", headers=_headers("ops:read")
        ).json()
        assert body["total"] == 1
        assert body["items"][0]["check_id"] == "data_source_down"

    def test_asset_type_filter(self, api):
        body = api.get(
            f"{BASE}/findings?asset_type=skill", headers=_headers("ops:read")
        ).json()
        assert body["total"] == 0

    def test_pagination_params_echoed(self, api):
        body = api.get(
            f"{BASE}/findings?page=1&page_size=1", headers=_headers("ops:read")
        ).json()
        assert body["total"] == 2
        assert len(body["items"]) == 1
        assert body["page"] == 1 and body["page_size"] == 1

    def test_invalid_pagination_422(self, api):
        assert api.get(
            f"{BASE}/findings?page=0", headers=_headers("ops:read")
        ).status_code == 422
        assert api.get(
            f"{BASE}/findings?page_size=101", headers=_headers("ops:read")
        ).status_code == 422

    def test_severity_orders_critical_first(self, api):
        body = api.get(f"{BASE}/findings", headers=_headers("ops:read")).json()
        assert body["items"][0]["severity"] == "critical"


class TestFindingLifecycle:
    """#50：详情查询 + ignore/reopen 流转、非法流转 409、乐观锁 409。"""

    @pytest.fixture
    def api(self, api_factory):
        # 一条 warning 问题（DEGRADED 同步任务），生命周期操作对象
        reader = _Reader([_source()], {"bjybdb": _job(SyncJobStatus.DEGRADED)})
        api = api_factory(reader)
        api.post(f"{BASE}/inspections", headers=_headers("ops:write"))
        return api

    @pytest.fixture
    def finding(self, api) -> dict:
        body = api.get(f"{BASE}/findings", headers=_headers("ops:read")).json()
        assert body["total"] == 1
        return body["items"][0]

    def test_get_detail_returns_finding_and_empty_timeline(self, api, finding):
        resp = api.get(f"{BASE}/findings/{finding['finding_id']}", headers=_headers("ops:read"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["finding"]["finding_id"] == finding["finding_id"]
        assert body["finding"]["payload"]["problem"] == "sync_job_degraded"
        assert body["events"] == []

    def test_get_detail_unknown_404(self, api):
        resp = api.get(f"{BASE}/findings/no-such-id", headers=_headers("ops:read"))
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "FINDING_NOT_FOUND"

    def test_ignore_records_reason_actor_and_event(self, api, finding):
        fid, revision = finding["finding_id"], finding["revision"]
        resp = api.post(
            f"{BASE}/findings/{fid}/ignore?expected_revision={revision}",
            json={"reason": "已知 DBA 排期维护，暂不处理"},
            headers=_headers("ops:write"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["finding"]["status"] == "ignored"
        assert body["finding"]["revision"] == revision + 1
        assert len(body["events"]) == 1
        event = body["events"][0]
        assert event["event_type"] == "ignored"
        assert event["reason"] == "已知 DBA 排期维护，暂不处理"
        assert event["actor"] == "ops-admin-1"

    def test_ignore_requires_reason_422(self, api, finding):
        resp = api.post(
            f"{BASE}/findings/{finding['finding_id']}/ignore?expected_revision=1",
            json={"reason": ""},
            headers=_headers("ops:write"),
        )
        assert resp.status_code == 422

    def test_ignore_twice_409_invalid_transition(self, api, finding):
        fid, revision = finding["finding_id"], finding["revision"]
        first = api.post(
            f"{BASE}/findings/{fid}/ignore?expected_revision={revision}",
            json={"reason": "先忽略"},
            headers=_headers("ops:write"),
        )
        assert first.status_code == 200
        second = api.post(
            f"{BASE}/findings/{fid}/ignore?expected_revision={first.json()['finding']['revision']}",
            json={"reason": "再忽略"},
            headers=_headers("ops:write"),
        )
        assert second.status_code == 409
        assert second.json()["detail"]["error_code"] == "FINDING_TRANSITION_INVALID"

    def test_ignore_with_stale_revision_409(self, api, finding):
        fid = finding["finding_id"]
        api.post(f"{BASE}/inspections", headers=_headers("ops:write"))  # 巡检刷新 revision
        resp = api.post(
            f"{BASE}/findings/{fid}/ignore?expected_revision={finding['revision']}",
            json={"reason": "过期版本"},
            headers=_headers("ops:write"),
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["error_code"] == "FINDING_REVISION_CONFLICT"

    def test_reopen_after_ignore_restores_open_with_event(self, api, finding):
        fid, revision = finding["finding_id"], finding["revision"]
        ignored = api.post(
            f"{BASE}/findings/{fid}/ignore?expected_revision={revision}",
            json={"reason": "暂时搁置"},
            headers=_headers("ops:write"),
        ).json()
        resp = api.post(
            f"{BASE}/findings/{fid}/reopen?expected_revision={ignored['finding']['revision']}",
            headers=_headers("ops:write"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["finding"]["status"] == "open"
        assert [event["event_type"] for event in body["events"]] == ["ignored", "reopened"]
        assert body["events"][1]["reason"] is None

    def test_reopen_from_open_409(self, api, finding):
        resp = api.post(
            f"{BASE}/findings/{finding['finding_id']}/reopen?expected_revision=1",
            headers=_headers("ops:write"),
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["error_code"] == "FINDING_TRANSITION_INVALID"

    def test_lifecycle_write_requires_ops_write(self, api, finding):
        fid = finding["finding_id"]
        assert api.post(
            f"{BASE}/findings/{fid}/ignore?expected_revision=1",
            json={"reason": "x"},
            headers=_headers("ops:read"),
        ).status_code == 403
        assert api.post(
            f"{BASE}/findings/{fid}/reopen?expected_revision=1",
            headers=_headers("ops:read"),
        ).status_code == 403

    def test_recurrence_does_not_resurrect_ignored_status(self, api, finding):
        fid, revision = finding["finding_id"], finding["revision"]
        api.post(
            f"{BASE}/findings/{fid}/ignore?expected_revision={revision}",
            json={"reason": "忽略后复现不复活"},
            headers=_headers("ops:write"),
        )
        api.post(f"{BASE}/inspections", headers=_headers("ops:write"))  # 复现巡检
        body = api.get(f"{BASE}/findings/{fid}", headers=_headers("ops:read")).json()
        assert body["finding"]["status"] == "ignored"  # 生命周期不被巡检覆盖
        assert body["finding"]["occurrence_count"] == 2
