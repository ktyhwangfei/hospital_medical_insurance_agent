"""提取契约端点 API 测试。

用内存注册表 + 重置语义层单例，确保 zcgz 种子数据存在且可隔离。
[依据: docs/steering/政策知识管线设计文档.md §7.1]
"""
import pytest

import src.semantic_layer.registry as reg_mod

BASE = "/api/v1/medical-insurance-ai-agent/semantic"


@pytest.fixture
def client(monkeypatch):
    """内存后端 + 重置单例，保证每次测试从干净种子开始。"""
    monkeypatch.setenv("USE_MEMORY_STORAGE", "1")
    reg_mod._semantic_registry_instance = None
    from fastapi.testclient import TestClient
    from src.runtime.api.app import create_app
    client = TestClient(create_app())
    yield client
    reg_mod._semantic_registry_instance = None


def test_unknown_object_returns_404(client):
    r = client.get(f"{BASE}/objects/no_such_object/extraction-schema")
    assert r.status_code == 404


def test_zcgz_contract_structure_when_all_draft(client):
    """种子 zcgz 19 指标均为 draft，契约 fields 应为空（发布流程在 P4 质量门禁）。"""
    r = client.get(f"{BASE}/objects/zcgz/extraction-schema")
    assert r.status_code == 200
    data = r.json()
    assert data["fields"] == []
    assert data["entities"] == []
    assert data["relations"] == []
    assert "schema_version" in data
    assert "dictionaries" in data


def test_zcgz_contract_returns_published_field(client):
    """手动把一条 zcgz 指标置为 published，验证契约返回它。"""
    reg = reg_mod.get_semantic_registry()
    store = reg._store
    m = store.get_metric("zcgz.insu_type")
    assert m is not None
    m.status = "published"
    m.indexed = True
    m.extraction_hint = "城镇职工/城乡居民"
    store.save_metric(m)

    r = client.get(f"{BASE}/objects/zcgz/extraction-schema")
    assert r.status_code == 200
    codes = [f["code"] for f in r.json()["fields"]]
    assert "insu_type" in codes
