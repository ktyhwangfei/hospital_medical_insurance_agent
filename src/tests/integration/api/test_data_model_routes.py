"""数据模型建模 API 测试 — /data-governance/models。

权限：data_governance:read/write；错误码 404/409/422 映射；
依赖注入 override get_data_modeling_service 注入内存存储。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.data_platform.storage.data_model.data_model_in_memory import (
    InMemoryDataModelStorage,
)
from src.runtime.api.app import create_app
from src.runtime.api.data_model_routes import get_data_modeling_service
from src.runtime.data_governance.modeling.service import DataModelingService

PREFIX = "/api/v1/medical-insurance-ai-agent/data-governance/models"
JWT_SECRET = "data-model-test-secret"


def _token(permissions: list[str]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": "admin-1",
        "roles": ["system_admin"],
        "permissions": permissions,
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    h = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    p = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(
        hmac.new(JWT_SECRET.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return f"Bearer {h}.{p}.{sig}"


READ = {"Authorization": _token(["data_governance:read"])}
WRITE = {"Authorization": _token(["data_governance:write"])}


def _model_payload(**kw):
    payload = {
        "model_code": "dwd_mz_settlement",
        "name": "门诊结算明细模型",
        "layer": "dwd",
        "grain": "trade_no",
        "entity_code": "settlement",
        "owner": "data_governance",
        "fields": [
            {"field_code": "trade_no", "name": "交易号", "data_type": "varchar", "field_role": "identifier"},
            {"field_code": "pooling_payment", "name": "统筹支付", "data_type": "decimal", "field_role": "fact"},
            {"field_code": "pooling_self_payment", "name": "统筹自付", "data_type": "decimal", "field_role": "fact"},
        ],
    }
    payload.update(kw)
    return payload


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    app = create_app()
    # 单例服务：override 工厂若每次新建内存存储，POST 与 GET 会落在不同实例
    service = DataModelingService(InMemoryDataModelStorage())
    app.dependency_overrides[get_data_modeling_service] = lambda: service
    return TestClient(app)


def _create(client: TestClient) -> dict:
    res = client.post(PREFIX, json=_model_payload(), headers=WRITE)
    assert res.status_code == 201, res.text
    return res.json()


class TestModelCrud:
    def test_create_and_get(self, client):
        created = _create(client)
        assert created["status"] == "draft"
        res = client.get(f"{PREFIX}/dwd_mz_settlement", headers=READ)
        assert res.status_code == 200
        assert res.json()["grain"] == "trade_no"

    def test_list(self, client):
        _create(client)
        res = client.get(PREFIX, headers=READ)
        assert [m["model_code"] for m in res.json()] == ["dwd_mz_settlement"]

    def test_duplicate_create_409(self, client):
        _create(client)
        res = client.post(PREFIX, json=_model_payload(), headers=WRITE)
        assert res.status_code == 409
        assert res.json()["detail"]["error_code"] == "DATA_MODEL_CONFLICT"

    def test_get_missing_404(self, client):
        res = client.get(f"{PREFIX}/ghost", headers=READ)
        assert res.status_code == 404

    def test_update_optimistic_lock(self, client):
        _create(client)
        payload = _model_payload(name="改名")
        res = client.put(f"{PREFIX}/dwd_mz_settlement?expected_revision=99", json=payload, headers=WRITE)
        assert res.status_code == 409
        res = client.put(f"{PREFIX}/dwd_mz_settlement?expected_revision=1", json=payload, headers=WRITE)
        assert res.status_code == 200
        assert res.json()["revision"] == 2

    def test_delete_draft(self, client):
        _create(client)
        res = client.delete(f"{PREFIX}/dwd_mz_settlement?expected_revision=1", headers=WRITE)
        assert res.status_code == 200
        assert client.get(f"{PREFIX}/dwd_mz_settlement", headers=READ).status_code == 404

    def test_requires_auth(self, client):
        assert client.get(PREFIX).status_code == 401
        assert client.post(PREFIX, json=_model_payload()).status_code == 401


class TestLifecycleApi:
    def test_publish_freezes_model(self, client):
        _create(client)
        res = client.post(f"{PREFIX}/dwd_mz_settlement/submit-review", headers=WRITE)
        res = client.post(f"{PREFIX}/dwd_mz_settlement/publish", headers=WRITE)
        assert res.status_code == 200
        assert res.json()["status"] == "published"
        res = client.put(
            f"{PREFIX}/dwd_mz_settlement?expected_revision=2",
            json=_model_payload(), headers=WRITE,
        )
        assert res.status_code == 422
        res = client.delete(f"{PREFIX}/dwd_mz_settlement?expected_revision=2", headers=WRITE)
        assert res.status_code == 422

    def test_publish_gate_422(self, client):
        # 空字段模型：创建合法（结构 validator 跳过），发布门槛拦截
        payload = _model_payload(fields=[])
        client.post(PREFIX, json=payload, headers=WRITE)
        res = client.post(f"{PREFIX}/dwd_mz_settlement/submit-review", headers=WRITE)
        res = client.post(f"{PREFIX}/dwd_mz_settlement/publish", headers=WRITE)
        assert res.status_code == 422

    def test_deprecate_terminal(self, client):
        _create(client)
        client.post(f"{PREFIX}/dwd_mz_settlement/submit-review", headers=WRITE)
        res = client.post(f"{PREFIX}/dwd_mz_settlement/publish", headers=WRITE)
        res = client.post(f"{PREFIX}/dwd_mz_settlement/deprecate", headers=WRITE)
        assert res.json()["status"] == "deprecated"
        res = client.post(f"{PREFIX}/dwd_mz_settlement/submit-review", headers=WRITE)
        res = client.post(f"{PREFIX}/dwd_mz_settlement/publish", headers=WRITE)
        assert res.status_code == 422


class TestMappingApi:
    def _mapping_payload(self, **kw):
        payload = {
            "model_code": "dwd_mz_settlement",
            "field_code": "pooling_payment",
            "source_id": "bjybdb",
            "physical_table": "mz_trade",
            "physical_column": "T_FundPay",
        }
        payload.update(kw)
        return payload

    def test_save_and_confirm(self, client):
        _create(client)
        res = client.put(
            f"{PREFIX}/dwd_mz_settlement/mappings", json=self._mapping_payload(), headers=WRITE,
        )
        assert res.status_code == 200
        assert res.json()["status"] == "draft"
        res = client.post(
            f"{PREFIX}/dwd_mz_settlement/mappings/pooling_payment/bjybdb/confirm", headers=WRITE,
        )
        assert res.json()["status"] == "confirmed"
        res = client.get(f"{PREFIX}/dwd_mz_settlement/mappings", headers=READ)
        assert len(res.json()) == 1

    def test_mapping_unknown_field_422(self, client):
        _create(client)
        res = client.put(
            f"{PREFIX}/dwd_mz_settlement/mappings",
            json=self._mapping_payload(field_code="ghost"), headers=WRITE,
        )
        assert res.status_code == 422

    def test_delete_confirmed_mapping_422(self, client):
        _create(client)
        client.put(f"{PREFIX}/dwd_mz_settlement/mappings", json=self._mapping_payload(), headers=WRITE)
        client.post(
            f"{PREFIX}/dwd_mz_settlement/mappings/pooling_payment/bjybdb/confirm", headers=WRITE,
        )
        res = client.delete(
            f"{PREFIX}/dwd_mz_settlement/mappings/pooling_payment/bjybdb?expected_revision=2",
            headers=WRITE,
        )
        assert res.status_code == 422
