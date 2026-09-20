"""政策问答主链路鉴权契约测试（P1）。

用户故事：未登录/无权限的调用方不得访问政策问答接口（患者与结算数据入口）。
覆盖：无 token 401、无 scope 403、有 policy_qa:ask 200、角色矩阵默认持有该 scope。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.config.security_policy.portal_roles import PORTAL_ROLE_PERMISSIONS
from src.gateway.auth.token_issuer import sign_token
from src.runtime.api.app import create_app

BASE = "/api/v1/medical-insurance-ai-agent/policy-qa"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", "policy-qa-auth-test-secret")
    return TestClient(create_app())


def _headers(permissions: list[str]) -> dict:
    token = sign_token(
        sub="qa-auth-tester", roles=["ops_admin"], permissions=permissions
    )
    return {"Authorization": f"Bearer {token}"}


class TestPolicyQAAuthContract:
    def test_history_without_token_is_401(self, client):
        resp = client.get(f"{BASE}/history")
        assert resp.status_code == 401
        assert resp.json()["detail"]["error_code"] == "AUTH_REQUIRED"

    def test_history_without_scope_is_403(self, client):
        resp = client.get(f"{BASE}/history", headers=_headers(["ops:read"]))
        assert resp.status_code == 403
        assert resp.json()["detail"]["error_code"] == "AUTH_FORBIDDEN"

    def test_history_with_scope_is_200(self, client):
        resp = client.get(f"{BASE}/history", headers=_headers(["policy_qa:ask"]))
        assert resp.status_code == 200
        assert "items" in resp.json()

    def test_stream_without_token_is_401(self, client):
        resp = client.post(f"{BASE}/stream", json={"question": "统筹自付怎么算"})
        assert resp.status_code == 401
        assert resp.json()["detail"]["error_code"] == "AUTH_REQUIRED"

    def test_patient_lookup_without_token_is_401(self, client):
        resp = client.get(f"{BASE}/patient-lookup", params={"key": "3301"})
        assert resp.status_code == 401


def test_every_portal_role_holds_policy_qa_ask():
    """policy_qa:ask 是业务入口：所有门户角色默认持有。"""
    for role, permissions in PORTAL_ROLE_PERMISSIONS.items():
        assert "policy_qa:ask" in permissions, f"角色 {role} 缺少 policy_qa:ask"
