"""健康运营 /ops 诊断 API 测试 — issue #51（发起诊断 + citations 硬约束 + 503 语义）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.data_platform.storage.ops.ops_in_memory import InMemoryOpsFindingStorage
from src.domain.ops.models import FindingDraft, OpsAssetType, OpsSeverity
from src.model_service.models import ModelResponse, TokenUsage
from src.runtime.api.app import create_app
from src.runtime.api.ops_routes import get_ops_diagnosis_service, get_ops_service
from src.runtime.ops.diagnosis import OpsDiagnosisService
from src.runtime.ops.service import OpsHealthService

BASE = "/api/v1/medical-insurance-ai-agent/ops"
JWT_SECRET = "ops-diag-test-secret"
NOW = datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)


def _headers(permission):
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": "ops-admin-1",
        "roles": ["system_admin"],
        "permissions": [permission],
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    enc = lambda obj: base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    signing_input = f"{enc(header)}.{enc(payload)}"
    signature = base64.urlsafe_b64encode(hmac.new(
        JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256
    ).digest()).decode().rstrip("=")
    return {"Authorization": f"Bearer {signing_input}.{signature}"}


class _EmptyReader:
    """健康服务巡检读取面（本测试不触发巡检，仅满足构造签名）。"""

    def list_sources(self):
        return []

    def get_job(self, source_id):
        raise LookupError(source_id)


class _FakeGateway:
    def __init__(self, content: str = "", error: Exception | None = None):
        self.content = content
        self.error = error

    def generate(self, messages, model_type, scene, **kwargs):
        if self.error is not None:
            raise self.error
        return ModelResponse(
            content=self.content,
            model_name="fake-diag-model",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
            finish_reason="stop",
        )


_COMPLETE = json.dumps({
    "root_cause": "同步任务连续失败，疑似源库连接超时",
    "citations": ["E1"],
    "uncertainties": ["缺少最近一次成功同步时间"],
    "actions": [
        {"level": "L1", "description": "重试同步任务", "citation_ids": ["E1"]},
        {"level": "L2", "description": "人工核对源库凭据", "citation_ids": ["E1"]},
    ],
})


@pytest.fixture
def api_factory(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)

    def build(gateway: _FakeGateway) -> TestClient:
        storage = InMemoryOpsFindingStorage()
        finding = storage.upsert_finding(
            FindingDraft(
                asset_type=OpsAssetType.DATA,
                asset_id="bjybdb",
                check_id="data_sync_failed",
                severity=OpsSeverity.CRITICAL,
                payload={"problem": "sync_job_failed", "job_status": "failed"},
            ),
            seen_at=NOW,
        )
        # 诊断与健康服务共享同一存储：GET 详情与 POST 诊断看到同一条 finding
        diagnosis = OpsDiagnosisService(
            storage, lambda: gateway, evidence_collector=lambda f: [],
        )
        health = OpsHealthService(storage, _EmptyReader)
        app = create_app()
        app.dependency_overrides[get_ops_diagnosis_service] = lambda: diagnosis
        app.dependency_overrides[get_ops_service] = lambda: health
        client = TestClient(app, raise_server_exceptions=False)
        client.finding_id = finding.finding_id  # type: ignore[attr-defined]
        return client

    return build


class TestDiagnoseAuth:
    def test_missing_token_401(self, api_factory):
        api = api_factory(_FakeGateway(_COMPLETE))
        assert api.post(f"{BASE}/findings/{api.finding_id}/diagnose").status_code == 401

    def test_read_permission_403(self, api_factory):
        api = api_factory(_FakeGateway(_COMPLETE))
        resp = api.post(
            f"{BASE}/findings/{api.finding_id}/diagnose", headers=_headers("ops:read"),
        )
        assert resp.status_code == 403


class TestDiagnose:
    def test_complete_report_saved(self, api_factory):
        api = api_factory(_FakeGateway(_COMPLETE))
        resp = api.post(
            f"{BASE}/findings/{api.finding_id}/diagnose", headers=_headers("ops:write"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["report"]["status"] == "complete"
        assert body["report"]["root_cause"]
        assert {a["level"] for a in body["report"]["actions"]} == {"L1", "L2"}
        assert body["report"]["model_route"]["scene"] == "asset_diagnosis"
        assert body["report"]["generated_by"] == "ops-admin-1"
        # 报告同时回填到 finding.diagnosis（详情页报告卡片数据源）
        assert body["finding"]["diagnosis"]["status"] == "complete"
        # 诊断只读：不动状态与乐观锁
        assert body["finding"]["status"] == "open"
        assert body["finding"]["revision"] == 1

    def test_insufficient_evidence_no_actions(self, api_factory):
        """验收负例（API 层）：无引用诊断落库 insufficient_evidence 且无建议动作。"""
        no_citations = json.dumps({
            "root_cause": "可能是网络问题",
            "citations": [],
            "uncertainties": ["证据不足"],
            "actions": [
                {"level": "L1", "description": "重试同步", "citation_ids": ["E1"]},
            ],
        })
        api = api_factory(_FakeGateway(no_citations))
        resp = api.post(
            f"{BASE}/findings/{api.finding_id}/diagnose", headers=_headers("ops:write"),
        )
        assert resp.status_code == 200
        report = resp.json()["report"]
        assert report["status"] == "insufficient_evidence"
        assert report["actions"] == []
        assert report["root_cause"] is None

    def test_model_failure_503_not_saved(self, api_factory):
        api = api_factory(_FakeGateway(error=RuntimeError("模型不可达")))
        resp = api.post(
            f"{BASE}/findings/{api.finding_id}/diagnose", headers=_headers("ops:write"),
        )
        assert resp.status_code == 503
        assert resp.json()["detail"]["error_code"] == "DIAGNOSIS_UNAVAILABLE"
        # 503 不落库：详情里 diagnosis 仍为空
        detail = api.get(
            f"{BASE}/findings/{api.finding_id}", headers=_headers("ops:read"),
        ).json()
        assert detail["finding"]["diagnosis"] is None

    def test_unknown_finding_404(self, api_factory):
        api = api_factory(_FakeGateway(_COMPLETE))
        resp = api.post(f"{BASE}/findings/missing/diagnose", headers=_headers("ops:write"))
        assert resp.status_code == 404
