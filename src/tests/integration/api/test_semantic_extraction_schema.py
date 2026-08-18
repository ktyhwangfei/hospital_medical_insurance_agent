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


def test_zcgz_contract_returns_all_seed_fields_after_publish(client):
    """种子后 zcgz 自动发布，契约应返回当前完整字段 + 5 政策字典。

    [来源: docs/steering/政策知识管线设计计划.md Phase 8.3 — zcgz 指标 published + value_domain]
    收口标准：契约含全部字段。
    """
    r = client.get(f"{BASE}/objects/zcgz/extraction-schema")
    assert r.status_code == 200
    data = r.json()
    codes = {f["code"] for f in data["fields"]}
    assert len(data["fields"]) == 22, f"期望 22 字段，实际 {len(data['fields'])}"
    assert {"personal_payment_ratio", "personal_payment_coefficient", "referenced_clause"} <= codes
    # 核心检索维度带索引 + 值域
    insu = next(f for f in data["fields"] if f["code"] == "insu_type")
    assert insu["indexed"] is True
    assert insu["value_domain"] == "insu_type"
    # 5 政策字典已解析
    assert set(data["dictionaries"]) == {
        "insu_type", "med_type", "hosp_lv", "psn_type", "setl_type",
    }
    assert "城镇职工基本医疗保险" in data["dictionaries"]["insu_type"]
    # 无实体/关系
    assert data["entities"] == []
    assert data["relations"] == []


def test_zcgz_contract_ignores_live_metric_changes_until_next_publish(client):
    """运行时契约锁定最新发布快照，live metric 修改不能污染已发布版本。"""
    reg = reg_mod.get_semantic_registry()
    store = reg._store
    m = store.get_metric("zcgz.insu_type")
    assert m is not None
    assert m.status == "published"  # P8.3 种子已发布
    m.extraction_hint = "城镇职工/城乡居民"
    store.save_metric(m)

    r = client.get(f"{BASE}/objects/zcgz/extraction-schema")
    assert r.status_code == 200
    insu = next(f for f in r.json()["fields"] if f["code"] == "insu_type")
    assert insu["extraction_hint"] != "城镇职工/城乡居民"
