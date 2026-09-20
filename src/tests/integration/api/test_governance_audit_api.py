"""治理写操作审计接线 API 测试 — Issue #75 验收 #4。

断言治理写端点把「操作人(取自 JWT 主体) + action + target_ref」写入审计面。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone

os.environ["USE_MEMORY_STORAGE"] = "1"

import pytest
from fastapi.testclient import TestClient

from src.data_platform.storage.workflow_config.in_memory import InMemoryWorkflowConfigStorage
from src.runtime.api import tool_workflow_routes
from src.runtime.api.app import create_app
from src.runtime.workflow import service as workflow_service
from src.runtime.workflow.config_service import WorkflowConfigService
from src.runtime.workflow.definitions import WF_REFUND_VERIFICATION

BASE = "/api/v1/medical-insurance-ai-agent/workflow-catalog"
JWT_SECRET = "governance-audit-test-secret"
WF = WF_REFUND_VERIFICATION.workflow_id


def _token(sub: str, permissions: list[str]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": sub,
        "roles": ["information_department"],
        "permissions": permissions,
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    encoded_header = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    encoded_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = base64.urlsafe_b64encode(
        hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return f"Bearer {signing_input}.{signature}"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    service = WorkflowConfigService(InMemoryWorkflowConfigStorage())
    app = create_app()
    app.dependency_overrides[tool_workflow_routes.get_workflow_config_service] = lambda: service
    monkeypatch.setattr(workflow_service, "get_workflow_config_service", lambda: service)
    workflow_service.invalidate_workflow_caches()
    with TestClient(app) as test_client:
        yield test_client
    workflow_service.invalidate_workflow_caches()


def test_workflow_config_write_records_governance_audit(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        tool_workflow_routes,
        "record_governance_action",
        lambda **kwargs: calls.append(kwargs),
    )

    response = client.put(
        f"{BASE}/workflows/{WF}/config",
        json={"enabled": False, "intent_keywords": None},
        headers={"Authorization": _token("workflow-admin-1", ["workflow:write"])},
    )

    assert response.status_code == 200
    # 审计能回答「谁在什么时候改了哪条治理配置」：actor 取自 JWT 主体（非自报）
    assert len(calls) == 1
    assert calls[0]["user_id"] == "workflow-admin-1"
    assert calls[0]["action"] == "workflow.config.update"
    assert calls[0]["target_ref"] == f"workflow_id={WF}"


def test_failed_write_records_no_audit(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        tool_workflow_routes,
        "record_governance_action",
        lambda **kwargs: calls.append(kwargs),
    )

    response = client.put(
        f"{BASE}/workflows/{WF}/config",
        json={"enabled": False, "intent_keywords": None},
        headers={"Authorization": _token("workflow-admin-1", ["workflow:read"])},
    )

    assert response.status_code == 403
    assert calls == []
