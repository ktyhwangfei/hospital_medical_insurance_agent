"""#62 验收③ 受控问数闭环：门诊加工视图快照端点（/semantic/query/processed-snapshot）。

只读已发布直接映射：stub 连接断言 SQL 指向视图、单行快照返回四值、
缺口径句/未注册/多行/未认证各拒止路径。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer


BASE = "/api/v1/medical-insurance-ai-agent/semantic"
JWT_SECRET = "processed-snapshot-test-secret"


def _review_headers() -> dict[str, str]:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": "semantic-reviewer",
        "roles": ["information_department"],
        "permissions": ["semantic:review"],
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    encoded_header = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    encoded_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = base64.urlsafe_b64encode(
        hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return {"Authorization": f"Bearer {signing_input}.{signature}"}


from datetime import timedelta  # noqa: E402  (置于 _review_headers 后可读性优先)


class _StubCursor:
    def __init__(self, rows, captured):
        self._rows = rows
        self._captured = captured

    def execute(self, sql):
        self._captured["sql"] = str(sql)

    def fetchall(self):
        return self._rows

    @property
    def description(self):
        return None


class _StubConnection:
    def __init__(self, rows, captured):
        self._captured = captured
        self._rows = rows

    def cursor(self):
        return _StubCursor(self._rows, self._captured)

    def close(self):
        self._captured["closed"] = True


@pytest.fixture
def api(monkeypatch):
    from src.runtime.api import semantic_routes

    store = InMemoryRegistryStore()
    seed_semantic_layer(store)  # 批次二 ensure：mzjyxx.op_* 四指标 published
    registry = SemanticRegistry(store)
    monkeypatch.setattr(semantic_routes, "get_registry", lambda: registry)
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    captured: dict = {}
    # 列序 = 指标按 metric_code 排序后的 SELECT 序：op_fund_pay, op_self_pay, op_total_fee, op_valid_settle_count
    monkeypatch.setattr(
        semantic_routes, "_connect_processed_view",
        lambda source, ds_id: _StubConnection(
            [(113.66, 6530.03, 6643.69, 12)], captured
        ),
    )
    return TestClient(create_app(), raise_server_exceptions=False), captured


def test_快照端点_返回四加工字段值(api):
    client, captured = api
    resp = client.get(f"{BASE}/query/processed-snapshot", headers=_review_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["view"] == "v_op_outpatient_processed"
    assert body["datasource_id"] == "bjybdb"
    assert "口径句 v4" in body["signoff"]
    values = {m["metric_code"]: m["value"] for m in body["metrics"]}
    assert values == {
        "mzjyxx.op_fund_pay": 113.66,
        "mzjyxx.op_self_pay": 6530.03,
        "mzjyxx.op_total_fee": 6643.69,
        "mzjyxx.op_valid_settle_count": 12.0,
    }
    first = body["metrics"][0]
    assert "口径句v4" in first["definition"]  # 口径句随结果可追溯
    assert "v_op_outpatient_processed" in captured["sql"]  # SQL 指向加工视图
    assert captured["closed"] is True


def test_快照端点_未注册指标404(monkeypatch):
    from src.runtime.api import semantic_routes

    store = InMemoryRegistryStore()  # 未 seed → 无 op_* 指标
    monkeypatch.setattr(semantic_routes, "get_registry", lambda: SemanticRegistry(store))
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    client = TestClient(create_app(), raise_server_exceptions=False)
    resp = client.get(f"{BASE}/query/processed-snapshot", headers=_review_headers())
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "SEMANTIC_PROCESSED_SNAPSHOT_UNMAPPED"


def test_快照端点_多行拒绝猜测(monkeypatch):
    from src.runtime.api import semantic_routes

    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    monkeypatch.setattr(semantic_routes, "get_registry", lambda: SemanticRegistry(store))
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    monkeypatch.setattr(
        semantic_routes, "_connect_processed_view",
        lambda source, ds_id: _StubConnection([(1, 2, 3, 4), (5, 6, 7, 8)], {}),
    )
    client = TestClient(create_app(), raise_server_exceptions=False)
    resp = client.get(f"{BASE}/query/processed-snapshot", headers=_review_headers())
    assert resp.status_code == 503
    assert resp.json()["detail"]["error_code"] == "SEMANTIC_PROCESSED_SNAPSHOT_AMBIGUOUS"


def test_快照端点_未认证401(monkeypatch):
    from src.runtime.api import semantic_routes

    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    monkeypatch.setattr(semantic_routes, "get_registry", lambda: SemanticRegistry(store))
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert client.get(f"{BASE}/query/processed-snapshot").status_code == 401
