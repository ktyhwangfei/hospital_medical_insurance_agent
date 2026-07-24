"""P7.1 datasource API 测试 — 数据源注册表 CRUD。

用内存假 store 替换 PolicyMetaStore，隔离 PG，纯 API 契约验证。
[依据: docs/steering/政策知识管线设计.md §7.6；开发计划 P7.1]
"""
import pytest

BASE = "/api/v1/medical-insurance-ai-agent/semantic/datasources"


class _FakeMetaStore:
    """PolicyMetaStore 的内存替身（仅实现 datasource CRUD，行为对齐 _ds_row）。"""

    def __init__(self):
        self._by_id: dict[str, dict] = {}
        self._seq = 0

    def register_datasource(self, name, ds_type, connection_config, ds_id=""):
        if not ds_id:
            self._seq += 1
            ds_id = f"ds_test_{self._seq}"
        self._by_id[ds_id] = {
            "id": ds_id, "name": name, "type": ds_type,
            "connection_config": connection_config, "enabled": True,
            "created_at": "2026-07-24T00:00:00Z",
        }
        return self._by_id[ds_id]

    def list_datasources(self, enabled_only=False):
        rows = list(self._by_id.values())
        return [r for r in rows if not enabled_only or r["enabled"]]

    def get_datasource(self, ds_id):
        return self._by_id.get(ds_id)

    def toggle_datasource(self, ds_id, enabled):
        if ds_id in self._by_id:
            self._by_id[ds_id]["enabled"] = enabled


@pytest.fixture
def client(monkeypatch):
    """注入内存假 store，避免连真实 PG。"""
    import src.runtime.api.semantic_routes as sr
    fake = _FakeMetaStore()
    monkeypatch.setattr(sr, "_get_meta_store", lambda: fake)
    from fastapi.testclient import TestClient
    from src.runtime.api.app import create_app
    c = TestClient(create_app())
    yield c, fake


def test_list_empty(client):
    c, _ = client
    r = c.get(BASE)
    assert r.status_code == 200
    assert r.json() == []


def test_register_and_list(client):
    c, _ = client
    r = c.post(BASE, json={
        "name": "院内HIS", "type": "sqlserver",
        "connection_config": {"host": "h1", "db": "d1"},
    })
    assert r.status_code == 201
    ds = r.json()
    assert ds["id"]
    assert ds["name"] == "院内HIS"
    assert ds["type"] == "sqlserver"
    assert ds["enabled"] is True
    assert ds["connection_config"]["host"] == "h1"

    assert len(c.get(BASE).json()) == 1


def test_get_by_id_and_404(client):
    c, _ = client
    r = c.get(f"{BASE}/no_such")
    assert r.status_code == 404

    created = c.post(BASE, json={
        "name": "Milvus政策库", "type": "milvus", "connection_config": {},
    }).json()
    r = c.get(f"{BASE}/{created['id']}")
    assert r.status_code == 200
    assert r.json()["name"] == "Milvus政策库"


def test_toggle_enabled_and_filter(client):
    c, _ = client
    created = c.post(BASE, json={
        "name": "ds", "type": "sqlserver", "connection_config": {},
    }).json()
    r = c.patch(f"{BASE}/{created['id']}", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    # 未过滤：仍可见
    assert len(c.get(BASE).json()) == 1
    # enabled_only 过滤：禁用的不返回
    assert len(c.get(f"{BASE}?enabled_only=true").json()) == 0


def test_toggle_unknown_returns_404(client):
    c, _ = client
    r = c.patch(f"{BASE}/no_such", json={"enabled": False})
    assert r.status_code == 404


def test_register_validates_required_name(client):
    c, _ = client
    # 缺 name 应 422（Pydantic 校验）
    r = c.post(BASE, json={"type": "sqlserver", "connection_config": {}})
    assert r.status_code == 422
