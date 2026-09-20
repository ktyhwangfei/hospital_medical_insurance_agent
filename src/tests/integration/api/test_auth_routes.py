"""门户认证 API 测试 — Issue #75（login/refresh/logout/me + 权限矩阵端到端）。"""
from __future__ import annotations

import base64
import json
import os

os.environ["USE_MEMORY_STORAGE"] = "1"

import pytest
from fastapi.testclient import TestClient

from src.domain.portal_account import PortalAccount, PortalPasswordHasher
from src.gateway.auth import authenticator
from src.runtime.api import auth_routes
from src.runtime.api.app import create_app
from src.runtime.portal_auth.service import PortalAuthService
from src.data_platform.storage.portal_account import InMemoryPortalAccountStore

JWT_SECRET = "portal-auth-test-secret"
API = "/api/v1/medical-insurance-ai-agent"


def _make_service(accounts: dict[str, str]) -> PortalAuthService:
    store = InMemoryPortalAccountStore()
    hasher = PortalPasswordHasher()
    for username, role in accounts.items():
        store.create_account(
            PortalAccount(
                username=username,
                password_hash=hasher.hash_password(f"{username}-pass"),
                role=role,
            )
        )
    return PortalAuthService(store)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    authenticator.reset()
    service = _make_service({"admin-user": "admin", "viewer-user": "reviewer"})
    app = create_app()
    app.dependency_overrides[auth_routes.get_portal_auth_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client
    authenticator.reset()


def _login(client: TestClient, username: str) -> str:
    response = client.post(
        f"{API}/auth/login", json={"username": username, "password": f"{username}-pass"}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


class TestLogin:
    def test_login_issues_token_with_role_permissions(self, client):
        token = _login(client, "admin-user")

        payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
        assert payload["sub"] == "admin-user"
        assert payload["roles"] == ["admin"]
        assert "workflow:write" in payload["permissions"]
        assert payload["exp"] - payload["iat"] == 7200

    def test_reviewer_gets_minimal_permissions(self, client):
        token = _login(client, "viewer-user")
        payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
        # policy_qa:ask 为业务入口默认权限（P1）
        assert payload["permissions"] == ["policy_qa:ask", "semantic:review"]

    def test_wrong_password_returns_401_without_leakage(self, client):
        response = client.post(
            f"{API}/auth/login",
            json={"username": "no-such-user", "password": "whatever"},
        )

        assert response.status_code == 401
        assert response.json()["detail"]["error_code"] == "AUTH_INVALID_CREDENTIALS"

    def test_rate_limit_after_repeated_failures(self, client):
        for _ in range(5):
            client.post(
                f"{API}/auth/login", json={"username": "admin-user", "password": "bad"}
            )
        response = client.post(
            f"{API}/auth/login", json={"username": "admin-user", "password": "bad"}
        )

        assert response.status_code == 429
        assert response.json()["detail"]["error_code"] == "RATE_LIMITED"

    def test_login_requires_jwt_secret(self, client, monkeypatch):
        monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)
        response = client.post(
            f"{API}/auth/login",
            json={"username": "admin-user", "password": "admin-user-pass"},
        )
        # fail-closed：密钥缺失，签发显式不可用（绝不回退假数据）
        assert response.status_code == 503
        assert response.json()["detail"]["error_code"] == "AUTH_SIGNING_UNAVAILABLE"


class TestRefreshAndMe:
    def test_refresh_issues_new_token(self, client):
        token = _login(client, "viewer-user")

        response = client.post(
            f"{API}/auth/refresh", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        new_token = response.json()["access_token"]
        # iat/exp 为秒级精度：同秒续签可能与原 token 相同，只断言语义有效
        old_payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
        new_payload = json.loads(base64.urlsafe_b64decode(new_token.split(".")[1] + "=="))
        assert new_payload["exp"] >= old_payload["exp"]
        assert new_payload["sub"] == old_payload["sub"]
        me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {new_token}"})
        assert me.status_code == 200
        assert me.json()["user_id"] == "viewer-user"
        assert me.json()["permissions"] == ["policy_qa:ask", "semantic:review"]

    def test_refresh_beyond_absolute_limit_rejected(self, client, monkeypatch):
        monkeypatch.setattr(
            "src.runtime.portal_auth.service.REFRESH_ABSOLUTE_LIMIT_SECONDS", -1
        )
        token = _login(client, "admin-user")

        response = client.post(
            f"{API}/auth/refresh", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401
        assert response.json()["detail"]["error_code"] == "EXPIRED_TOKEN"

    def test_me_without_token_returns_401(self, client):
        response = client.get(f"{API}/auth/me")

        assert response.status_code == 401
        assert response.json()["detail"]["error_code"] == "AUTH_REQUIRED"


class TestLogout:
    def test_logout_blacklists_token(self, client):
        token = _login(client, "admin-user")
        headers = {"Authorization": f"Bearer {token}"}

        logout = client.post(f"{API}/auth/logout", headers=headers)
        assert logout.status_code == 200

        me = client.get(f"{API}/auth/me", headers=headers)
        assert me.status_code == 401


class TestLoginGrantsGovernanceAccess:
    """验收 #1/#2：登录签发的 token 必须能过治理写接口的既有校验。"""

    def test_admin_token_passes_workflow_write_check(self, client):
        token = _login(client, "admin-user")

        auth = authenticator.validate_signed_token(f"Bearer {token}")
        permitted = authenticator.check_permission(auth, "workflow:write")

        assert permitted.is_success

    def test_reviewer_token_denied_workflow_write(self, client):
        token = _login(client, "viewer-user")

        auth = authenticator.validate_signed_token(f"Bearer {token}")
        permitted = authenticator.check_permission(auth, "workflow:write")

        assert not permitted.is_success
        assert permitted.status.value == "insufficient_permission"
