"""Workflow 治理配置 API 测试：鉴权 + 写入后路由/目录同进程立即生效。

覆盖 issue：院区个性化（关键词/启停）不再改代码重发版。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.data_platform.storage.workflow_config.in_memory import InMemoryWorkflowConfigStorage
from src.runtime.api.app import create_app
from src.runtime.api.tool_workflow_routes import get_workflow_config_service
from src.runtime.workflow import service as workflow_service
from src.runtime.workflow.config_service import WorkflowConfigService
from src.runtime.workflow.definitions import WF_REFUND_VERIFICATION

BASE = "/api/v1/medical-insurance-ai-agent/workflow-catalog"
JWT_SECRET = "workflow-config-test-secret"
WF = WF_REFUND_VERIFICATION.workflow_id
CUSTOM_KEYWORD = "多收钱了怎么办"


def _token(permissions):
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": "workflow-admin-1",
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


WRITE_HEADERS = {"Authorization": _token(["workflow:write"])}
READ_ONLY_HEADERS = {"Authorization": _token(["workflow:read"])}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    monkeypatch.delenv("WORKFLOW_DISABLED", raising=False)
    monkeypatch.delenv("PLATFORM_HOSPITAL_CODE", raising=False)
    service = WorkflowConfigService(InMemoryWorkflowConfigStorage())
    app = create_app()
    app.dependency_overrides[get_workflow_config_service] = lambda: service
    # 路由侧走的是单例工厂；测试patch 到同一内存服务，才能验证"写入立即生效"
    monkeypatch.setattr(workflow_service, "get_workflow_config_service", lambda: service)
    workflow_service.invalidate_workflow_caches()
    with TestClient(app) as test_client:
        yield test_client
    workflow_service.invalidate_workflow_caches()


def _catalog_item(test_client, workflow_id: str) -> dict:
    response = test_client.get(f"{BASE}/workflows")
    assert response.status_code == 200
    return {item["workflow_id"]: item for item in response.json()["items"]}[workflow_id]


def test_write_requires_workflow_write_permission(client) -> None:
    body = {"enabled": False, "intent_keywords": None}
    assert client.put(f"{BASE}/workflows/{WF}/config", json=body).status_code == 401
    assert (
        client.put(
            f"{BASE}/workflows/{WF}/config", json=body, headers=READ_ONLY_HEADERS
        ).status_code
        == 403
    )


def test_keyword_override_takes_effect_without_restart(client) -> None:
    """写入关键词后，同进程路由立即按新词命中（无需重启）。"""
    assert workflow_service.route_workflow_question(CUSTOM_KEYWORD) is None

    response = client.put(
        f"{BASE}/workflows/{WF}/config",
        json={"enabled": True, "intent_keywords": [CUSTOM_KEYWORD]},
        headers=WRITE_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["source"] == "global"
    assert response.json()["intent_keywords"] == [CUSTOM_KEYWORD]

    routed = workflow_service.route_workflow_question(CUSTOM_KEYWORD)
    assert routed is not None and routed.workflow_id == WF

    item = _catalog_item(client, WF)
    assert item["keyword_source"] == "global"
    assert item["intent_keywords"] == [CUSTOM_KEYWORD]


def test_disable_removes_workflow_from_routing(client) -> None:
    client.put(
        f"{BASE}/workflows/{WF}/config",
        json={"enabled": True, "intent_keywords": [CUSTOM_KEYWORD]},
        headers=WRITE_HEADERS,
    )
    assert workflow_service.route_workflow_question(CUSTOM_KEYWORD) is not None

    response = client.put(
        f"{BASE}/workflows/{WF}/config",
        json={"enabled": False},
        headers=WRITE_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    # 省略 intent_keywords = 保持该行已有词表（只改启停不丢院区关键词）
    assert response.json()["intent_keywords"] == [CUSTOM_KEYWORD]

    assert workflow_service.route_workflow_question(CUSTOM_KEYWORD) is None
    assert _catalog_item(client, WF)["enabled"] is False


def test_explicit_null_keywords_reset_to_code_default(client) -> None:
    client.put(
        f"{BASE}/workflows/{WF}/config",
        json={"enabled": True, "intent_keywords": [CUSTOM_KEYWORD]},
        headers=WRITE_HEADERS,
    )
    response = client.put(
        f"{BASE}/workflows/{WF}/config",
        json={"enabled": True, "intent_keywords": None},
        headers=WRITE_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["intent_keywords"] == list(WF_REFUND_VERIFICATION.intent_keywords)


def test_unknown_workflow_returns_404(client) -> None:
    response = client.put(
        f"{BASE}/workflows/wf_not_registered/config",
        json={"enabled": False, "intent_keywords": None},
        headers=WRITE_HEADERS,
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "WORKFLOW_NOT_FOUND"


def test_invalid_body_rejected(client) -> None:
    response = client.put(
        f"{BASE}/workflows/{WF}/config",
        json={"enabled": True, "intent_keywords": None, "unknown_field": 1},
        headers=WRITE_HEADERS,
    )
    assert response.status_code == 422
