"""健康运营 /ops API 测试 — issue #45 P0（鉴权 + 巡检去重 + 列表过滤分页）
+ #50（详情 / ignore / reopen 状态机与乐观锁）
+ #54（L2 人工确认修复流：manual-handoff / manual-complete 与负例）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any

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
from src.domain.ops.models import OpsInspectionTrigger, RemediationRiskLevel
from src.runtime.api.app import create_app
from src.runtime.api.ops_routes import get_ops_inspection_scheduler, get_ops_service
from src.runtime.ops.remediation import RemediationActionOutcome, RemediationSpec
from src.runtime.ops.scheduler import OpsInspectionScheduler
from src.runtime.ops.service import OpsHealthService
from src.runtime.task_closure import service as task_service

BASE = "/api/v1/medical-insurance-ai-agent/ops"
JWT_SECRET = "ops-test-secret"
NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


class _FakeTaskStore:
    """task_closure 内存替身（#54 人工确认任务）：避免写活库 tasks 表。"""

    def __init__(self):
        self._tasks: dict[str, dict[str, Any]] = {}

    def save_task(self, task):
        self._tasks[task["task_id"]] = task
        return task

    def get_task(self, task_id):
        return self._tasks.get(task_id)

    def create_task(self, task_id, task_type, description, responsible_role,
                    workflow_id=None, **kwargs):
        task = {
            "task_id": task_id, "task_type": task_type, "description": description,
            "responsible_role": responsible_role,
            "status": kwargs.get("status", "pending"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if workflow_id is not None:
            task["workflow_id"] = workflow_id
        for key in ("input_data", "output_data"):
            if kwargs.get(key) is not None:
                task[key] = kwargs[key]
        return self.save_task(task)

    def list_tasks_by_workflow(self, workflow_id):
        return [t for t in self._tasks.values() if t.get("workflow_id") == workflow_id]


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
        # 相对真实时钟取未来值：巡检/修复验证用 datetime.now 判定滞后，
        # 固定历史日期会让健康任务随日历推进被判 lagging（时间炸弹）
        next_run_at=datetime.now(timezone.utc) + timedelta(minutes=5),
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


def _fake_executor(outcome: RemediationActionOutcome):
    return lambda finding, actor: outcome


def _fake_whitelist(executor):
    return (RemediationSpec(
        action_id="retry_data_sync",
        check_id="data_sync_failed",
        risk_level=RemediationRiskLevel.L1,
        description="重试门诊同步（测试）",
        executor=executor,
    ),)


@pytest.fixture
def api_factory(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    # #54：人工确认任务走 task_closure 进程单例，测试替换为内存替身防写活库
    monkeypatch.setattr(task_service, "_task_store", _FakeTaskStore())

    def build(reader, *, executor=None, storage=None) -> TestClient:
        # 依赖注入必须复用同一服务实例：lambda 内 new 存储会让每个请求拿到空库
        # （#52 起 POST /inspections 走调度器，须与问题库服务共享同一存储）
        whitelist = _fake_whitelist(executor) if executor else None
        shared = storage if storage is not None else InMemoryOpsFindingStorage()
        service = OpsHealthService(shared, lambda: reader, whitelist)
        scheduler = OpsInspectionScheduler(shared, service)
        app = create_app()
        app.dependency_overrides[get_ops_service] = lambda: service
        app.dependency_overrides[get_ops_inspection_scheduler] = lambda: scheduler
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


class TestInspectionScheduling:
    """#52：手动巡检写运行留痕 + 执行中 409 + 摘要端点。"""

    def test_manual_inspection_returns_run_fields(self, api_factory):
        api = api_factory(_Reader(
            [_source(ConnectionStatus.ERROR)],
            {"bjybdb": _job(SyncJobStatus.FAILED)},
        ))
        body = api.post(f"{BASE}/inspections", headers=_headers("ops:write")).json()
        assert body["trigger_source"] == "manual"
        assert body["inspection_id"]
        assert body["new_finding_count"] == 2  # 首巡检两条问题均为首见

        # 第二次巡检：复现累计，不再是新发现
        second = api.post(f"{BASE}/inspections", headers=_headers("ops:write")).json()
        assert second["finding_count"] == 2
        assert second["new_finding_count"] == 0

    def test_in_progress_returns_409(self, api_factory):
        storage = InMemoryOpsFindingStorage()
        # 预占一个 running 位（模拟定时巡检执行中），手动触发应被拒
        claimed = storage.claim_inspection(
            datetime.now(timezone.utc),
            trigger_source=OpsInspectionTrigger.SCHEDULED,
            triggered_by="system:ops-scheduler",
        )
        assert claimed is not None
        api = api_factory(_Reader(), storage=storage)
        resp = api.post(f"{BASE}/inspections", headers=_headers("ops:write"))
        assert resp.status_code == 409
        assert resp.json()["detail"]["error_code"] == "INSPECTION_IN_PROGRESS"

    def test_summary_endpoint_shape_and_auth(self, api_factory):
        api = api_factory(_Reader())
        assert api.get(f"{BASE}/inspection-summary").status_code == 401
        assert api.get(
            f"{BASE}/inspection-summary", headers=_headers("ops:write")
        ).status_code == 403

        empty = api.get(f"{BASE}/inspection-summary", headers=_headers("ops:read")).json()
        assert empty["latest"] is None
        assert empty["in_progress"] is False
        assert empty["interval_minutes"] == 1440  # 默认每日

        api.post(f"{BASE}/inspections", headers=_headers("ops:write"))
        body = api.get(f"{BASE}/inspection-summary", headers=_headers("ops:read")).json()
        assert body["latest"]["status"] == "succeeded"
        assert body["latest"]["trigger_source"] == "manual"
        assert body["latest"]["finished_at"] is not None
        assert body["next_run_at"] is not None


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


class TestRemediation:
    """#53：L1 白名单修复端点 + 强制验证闭环 + 非白名单 409 负例。"""

    EXECUTED = RemediationActionOutcome(
        executed=True,
        before_evidence={"job_status": "failed"},
        after_evidence={"job_status": "running"},
    )

    @pytest.fixture
    def harness(self, api_factory):
        """失败同步任务 → 巡检落库 open finding；reader 可切换以驱动验证结果。"""
        reader = _Reader([_source()], {"bjybdb": _job(SyncJobStatus.FAILED)})
        api = api_factory(reader, executor=_fake_executor(self.EXECUTED))
        api.post(f"{BASE}/inspections", headers=_headers("ops:write"))
        body = api.get(f"{BASE}/findings", headers=_headers("ops:read")).json()
        assert body["total"] == 1
        return api, reader, body["items"][0]

    def _remediate(self, api, finding, revision=None):
        return api.post(
            f"{BASE}/findings/{finding['finding_id']}/remediate"
            f"?expected_revision={revision or finding['revision']}",
            headers=_headers("ops:write"),
        )

    def test_actions_endpoint_lists_whitelist(self, api_factory):
        api = api_factory(_Reader())
        resp = api.get(f"{BASE}/remediation-actions", headers=_headers("ops:read"))
        assert resp.status_code == 200
        body = resp.json()
        assert [(a["action"], a["check_id"], a["risk_level"]) for a in body] == [
            ("retry_data_sync", "data_sync_failed", "L1"),
        ]
        assert body[0]["description"]

    def test_verification_pass_resolves_finding(self, harness):
        api, reader, finding = harness
        reader._jobs["bjybdb"] = _job(SyncJobStatus.RUNNING)  # 修复后任务健康
        resp = self._remediate(api, finding)
        assert resp.status_code == 200
        body = resp.json()
        assert body["run"]["status"] == "succeeded"
        assert body["run"]["verification_result"] == "passed"
        assert body["run"]["action"] == "retry_data_sync"
        assert body["run"]["created_by"] == "ops-admin-1"
        assert body["detail"]["finding"]["status"] == "resolved"
        assert [e["event_type"] for e in body["detail"]["events"]] == ["resolved"]
        assert [r["run_id"] for r in body["detail"]["remediations"]] == [body["run"]["run_id"]]

    def test_verification_fail_keeps_open_and_accumulates(self, harness):
        api, _reader, finding = harness  # 任务仍 failed → 验证未通过
        resp = self._remediate(api, finding)
        assert resp.status_code == 200
        body = resp.json()
        assert body["run"]["verification_result"] == "failed"
        assert body["detail"]["finding"]["status"] == "open"
        assert body["detail"]["finding"]["occurrence_count"] == 2

    def test_action_not_executed_records_failed_run(self, api_factory):
        reader = _Reader([_source()], {"bjybdb": _job(SyncJobStatus.FAILED)})
        outcome = RemediationActionOutcome(
            executed=False, after_evidence={"error": "任务处于 paused 状态，不自动重试"},
        )
        api = api_factory(reader, executor=_fake_executor(outcome))
        api.post(f"{BASE}/inspections", headers=_headers("ops:write"))
        finding = api.get(f"{BASE}/findings", headers=_headers("ops:read")).json()["items"][0]

        resp = self._remediate(api, finding)
        assert resp.status_code == 200
        body = resp.json()
        assert body["run"]["status"] == "failed"
        assert body["run"]["verification_result"] is None
        assert body["detail"]["finding"]["status"] == "open"
        assert body["detail"]["finding"]["occurrence_count"] == 1

    def test_non_whitelisted_check_409(self, api_factory):
        # 连接探测失败不在白名单：无自动修复入口（负例）
        reader = _Reader([_source(ConnectionStatus.ERROR)], {})
        api = api_factory(reader, executor=_fake_executor(self.EXECUTED))
        api.post(f"{BASE}/inspections", headers=_headers("ops:write"))
        body = api.get(f"{BASE}/findings", headers=_headers("ops:read")).json()
        finding = next(f for f in body["items"] if f["check_id"] == "data_source_down")

        resp = self._remediate(api, finding)
        assert resp.status_code == 409
        assert resp.json()["detail"]["error_code"] == "REMEDIATION_NOT_WHITELISTED"
        detail = api.get(
            f"{BASE}/findings/{finding['finding_id']}", headers=_headers("ops:read")
        ).json()
        assert detail["remediations"] == []

    def test_stale_revision_409(self, harness):
        api, reader, finding = harness
        api.post(f"{BASE}/inspections", headers=_headers("ops:write"))  # 复现使 revision+1
        reader._jobs["bjybdb"] = _job(SyncJobStatus.RUNNING)  # 验证走通过路径才会触发流转
        resp = self._remediate(api, finding)  # 携带旧 revision
        assert resp.status_code == 409
        assert resp.json()["detail"]["error_code"] == "FINDING_REVISION_CONFLICT"

    def test_remediate_on_ignored_409(self, harness):
        api, _reader, finding = harness
        ignored = api.post(
            f"{BASE}/findings/{finding['finding_id']}/ignore?expected_revision=1",
            json={"reason": "排期维护"},
            headers=_headers("ops:write"),
        )
        assert ignored.status_code == 200
        resp = self._remediate(api, finding, revision=ignored.json()["finding"]["revision"])
        assert resp.status_code == 409
        assert resp.json()["detail"]["error_code"] == "FINDING_TRANSITION_INVALID"

    def test_remediate_requires_ops_write(self, harness):
        api, _reader, finding = harness
        resp = api.post(
            f"{BASE}/findings/{finding['finding_id']}/remediate?expected_revision=1",
            headers=_headers("ops:read"),
        )
        assert resp.status_code == 403

    def test_detail_unknown_404(self, api_factory):
        api = api_factory(_Reader())
        resp = api.post(f"{BASE}/findings/no-such-id/remediate?expected_revision=1",
                        headers=_headers("ops:write"))
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "FINDING_NOT_FOUND"


class TestManualFlow:
    """#54：L2 人工确认修复流——转人工、完成复检回链、负例与鉴权。"""

    @pytest.fixture
    def harness(self, api_factory):
        """DEGRADED 同步任务 → 巡检落库 open finding；reader 可切换驱动复检结果。"""
        reader = _Reader([_source()], {"bjybdb": _job(SyncJobStatus.DEGRADED)})
        api = api_factory(reader)
        api.post(f"{BASE}/inspections", headers=_headers("ops:write"))
        body = api.get(f"{BASE}/findings", headers=_headers("ops:read")).json()
        assert body["total"] == 1
        return api, reader, body["items"][0]

    def _request(self, api, finding, revision=None, *, note=None):
        return api.post(
            f"{BASE}/findings/{finding['finding_id']}/manual-handoff"
            f"?expected_revision={revision or finding['revision']}",
            json={"note": note},
            headers=_headers("ops:write"),
        )

    def _complete(self, api, finding_id, revision, *, result_note="已在治理页修正"):
        return api.post(
            f"{BASE}/findings/{finding_id}/manual-complete"
            f"?expected_revision={revision}",
            json={"result_note": result_note},
            headers=_headers("ops:write"),
        )

    def test_manual_endpoints_require_auth_and_ops_write(self, harness):
        api, _reader, finding = harness
        fid = finding["finding_id"]
        # 无 token → 401
        assert api.post(
            f"{BASE}/findings/{fid}/manual-handoff?expected_revision=1",
            json={"note": None},
        ).status_code == 401
        assert api.post(
            f"{BASE}/findings/{fid}/manual-complete?expected_revision=1",
            json={"result_note": "x"},
        ).status_code == 401
        # 只读权限 → 403
        assert api.post(
            f"{BASE}/findings/{fid}/manual-handoff?expected_revision=1",
            json={"note": None},
            headers=_headers("ops:read"),
        ).status_code == 403
        assert api.post(
            f"{BASE}/findings/{fid}/manual-complete?expected_revision=1",
            json={"result_note": "x"},
            headers=_headers("ops:read"),
        ).status_code == 403

    def test_request_moves_finding_to_waiting_human_with_task(self, harness):
        api, _reader, finding = harness
        resp = self._request(api, finding, note="非白名单问题，转人工处理")
        assert resp.status_code == 200
        body = resp.json()
        assert body["detail"]["finding"]["status"] == "waiting_human"
        assert body["detail"]["finding"]["revision"] == 2
        manual = body["manual_task"]
        assert manual["status"] == "waiting_human_confirmation"
        assert manual["target"] == "external"  # 数据资产 → 外部系统
        assert manual["requested_by"] == "ops-admin-1"
        assert manual["note"] == "非白名单问题，转人工处理"
        assert manual["task_id"].startswith("opsmanual_")
        # 详情回读同样携带人工任务（回链展示）
        detail = api.get(
            f"{BASE}/findings/{finding['finding_id']}", headers=_headers("ops:read")
        ).json()
        assert detail["finding"]["status"] == "waiting_human"
        assert detail["manual_task"]["task_id"] == manual["task_id"]
        assert [e["event_type"] for e in detail["events"]] == ["manual_requested"]

    def test_request_on_ignored_finding_409(self, harness):
        api, _reader, finding = harness
        ignored = api.post(
            f"{BASE}/findings/{finding['finding_id']}/ignore?expected_revision=1",
            json={"reason": "排期维护"},
            headers=_headers("ops:write"),
        )
        assert ignored.status_code == 200
        resp = self._request(api, finding, revision=ignored.json()["finding"]["revision"])
        assert resp.status_code == 409
        assert resp.json()["detail"]["error_code"] == "FINDING_TRANSITION_INVALID"

    def test_complete_after_fix_resolves_with_backfill(self, harness):
        api, reader, finding = harness
        fid = finding["finding_id"]
        requested = self._request(api, finding).json()
        task_id = requested["manual_task"]["task_id"]
        reader._jobs["bjybdb"] = _job(SyncJobStatus.READY)  # 治理页修复后任务健康
        resp = self._complete(api, fid, requested["detail"]["finding"]["revision"])
        assert resp.status_code == 200
        body = resp.json()
        assert body["detail"]["finding"]["status"] == "resolved"
        assert body["detail"]["finding"]["revision"] == 3
        manual = body["manual_task"]
        assert manual["task_id"] == task_id
        assert manual["status"] == "completed"
        assert manual["handled_by"] == "ops-admin-1"
        assert manual["result_note"] == "已在治理页修正"
        assert manual["handled_at"]
        assert [e["event_type"] for e in body["detail"]["events"]] == [
            "manual_requested", "resolved",
        ]

    def test_complete_with_still_failing_check_reopens(self, harness):
        api, _reader, finding = harness
        fid = finding["finding_id"]
        requested = self._request(api, finding).json()
        # 不修 reader：任务仍 DEGRADED → 复检仍报，回 open 且累计复现
        resp = self._complete(api, fid, requested["detail"]["finding"]["revision"],
                              result_note="修了但没修好")
        assert resp.status_code == 200
        body = resp.json()
        assert body["detail"]["finding"]["status"] == "open"
        assert body["detail"]["finding"]["occurrence_count"] == 2
        assert body["manual_task"]["status"] == "completed"
        assert [e["event_type"] for e in body["detail"]["events"]] == [
            "manual_requested", "manual_completed",
        ]

    def test_remediate_and_ignore_blocked_while_waiting_human(self, harness):
        # 验收负例：未完成人工确认前，问题不得经 remediate/ignore 离开 waiting_human
        api, reader, finding = harness
        fid = finding["finding_id"]
        requested = self._request(api, finding).json()
        rev = requested["detail"]["finding"]["revision"]
        remediate = api.post(
            f"{BASE}/findings/{fid}/remediate?expected_revision={rev}",
            headers=_headers("ops:write"),
        )
        assert remediate.status_code == 409
        assert remediate.json()["detail"]["error_code"] == "FINDING_TRANSITION_INVALID"
        ignore = api.post(
            f"{BASE}/findings/{fid}/ignore?expected_revision={rev}",
            json={"reason": "想直接忽略"},
            headers=_headers("ops:write"),
        )
        assert ignore.status_code == 409
        # reopen 允许撤回人工处理（waiting_human → open）
        reopen = api.post(f"{BASE}/findings/{fid}/reopen?expected_revision={rev}",
                          headers=_headers("ops:write"))
        assert reopen.status_code == 200
        assert reopen.json()["finding"]["status"] == "open"

    def test_complete_without_prior_request_404(self, harness):
        api, _reader, finding = harness
        resp = self._complete(api, finding["finding_id"], 1)
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "MANUAL_TASK_NOT_FOUND"

    def test_double_complete_is_idempotent(self, harness):
        api, reader, finding = harness
        fid = finding["finding_id"]
        requested = self._request(api, finding).json()
        rev = requested["detail"]["finding"]["revision"]
        reader._jobs["bjybdb"] = _job(SyncJobStatus.READY)
        first = self._complete(api, fid, rev)
        assert first.status_code == 200
        second = self._complete(api, fid, first.json()["detail"]["finding"]["revision"])
        assert second.status_code == 200
        body = second.json()
        assert body["detail"]["finding"]["status"] == "resolved"
        assert len(body["detail"]["events"]) == 2  # 不新增事件
