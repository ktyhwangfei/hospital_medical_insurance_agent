"""阶段2：对象级版本快照 + 发布控制测试（数据层 / 内存实现）。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.runtime.api import semantic_routes as sr
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer


@pytest.fixture
def registry():
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    return SemanticRegistry(store)


class TestPublishObject:
    def test_publish_creates_first_version(self, registry):
        """首次发布：current_version='1'，status='published'，快照含该对象全部指标。"""
        version = registry.publish_object("zydyxx", changelog="初始发布")
        assert version.version == "1"
        assert version.object_code == "zydyxx"
        assert {m.metric_code for m in version.metrics} == {"zydyxx.bcqfje", "zydyxx.bcybnje"}
        obj = registry.get_object("zydyxx")
        assert obj.current_version == "1"
        assert obj.status == "published"

    def test_publish_increments_version(self, registry):
        """再发布：版本递增到 '2'，历史版本保留。"""
        registry.publish_object("zyfdxx")
        v2 = registry.publish_object("zyfdxx")
        assert v2.version == "2"
        assert registry.get_object("zyfdxx").current_version == "2"
        versions = registry.list_object_versions("zyfdxx")
        assert len(versions) == 2

    def test_publish_nonexistent_object_raises(self, registry):
        with pytest.raises(ValueError):
            registry.publish_object("nonexistent")

    def test_version_snapshot_is_immutable(self, registry):
        """版本快照冻结发布时的指标；之后改 live metric 不影响快照。"""
        registry.publish_object("zydyxx")
        metric = registry.get_metric("zydyxx.bcqfje")
        metric.name = "被修改的起付线"
        registry._store.save_metric(metric)
        snapshot = registry.get_object_version("zydyxx", "1")
        bcqfje = next(m for m in snapshot.metrics if m.metric_code == "zydyxx.bcqfje")
        assert bcqfje.name == "起付线"

    def test_version_id_unique(self, registry):
        v1 = registry.publish_object("zyjyxx")
        v2 = registry.publish_object("zyjyxx")
        assert v1.version_id != v2.version_id


class TestVersionQuery:
    def test_list_object_versions_ordered(self, registry):
        for _ in range(3):
            registry.publish_object("zydyxx")
        versions = registry.list_object_versions("zydyxx")
        assert [v.version for v in versions] == ["1", "2", "3"]

    def test_get_object_version_returns_none_if_not_exists(self, registry):
        assert registry.get_object_version("zydyxx", "99") is None

    def test_unpublished_object_has_no_versions(self, registry):
        """seed 对象初始 current_version=None，无版本快照。"""
        obj = registry.get_object("djxx")
        assert obj.current_version is None
        assert registry.list_object_versions("djxx") == []

    def test_version_snapshot_has_object_metadata(self, registry):
        v = registry.publish_object("zyfdxx", changelog="v1说明")
        assert v.snapshot["name"] == "住院分段"
        assert v.snapshot["domain_code"] == "ybjs"
        assert v.changelog == "v1说明"

    def test_version_metrics_carry_source_field(self, registry):
        """快照指标保留 source_field（阶段3 运行时锁定要用）。"""
        v = registry.publish_object("zydyxx")
        bcqfje = next(m for m in v.metrics if m.metric_code == "zydyxx.bcqfje")
        assert bcqfje.source_field == "yb_dyxxzy.bcqfje"
        assert bcqfje.importance == "core"


# ── API 层测试（publish / versions 端点）──

@pytest.fixture
def api_client(monkeypatch):
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    reg = SemanticRegistry(store)
    monkeypatch.setattr(sr, "get_registry", lambda: reg)
    app = FastAPI()
    app.include_router(sr.router)
    return TestClient(app), reg


class TestPublishAPI:
    _BASE = "/api/v1/medical-insurance-ai-agent/semantic"

    def test_publish_endpoint(self, api_client):
        client, _ = api_client
        resp = client.post(f"{self._BASE}/objects/zydyxx/publish",
                           json={"changelog": "API发布"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "1"
        assert data["object_code"] == "zydyxx"
        assert data["metric_count"] == 2
        assert data["changelog"] == "API发布"

    def test_publish_nonexistent_returns_404(self, api_client):
        client, _ = api_client
        resp = client.post(f"{self._BASE}/objects/nope/publish", json={})
        assert resp.status_code == 404

    def test_list_versions_endpoint(self, api_client):
        client, reg = api_client
        reg.publish_object("zyfdxx")
        reg.publish_object("zyfdxx")
        resp = client.get(f"{self._BASE}/objects/zyfdxx/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert [d["version"] for d in data] == ["1", "2"]

    def test_get_version_detail_endpoint(self, api_client):
        client, reg = api_client
        reg.publish_object("zydyxx")
        resp = client.get(f"{self._BASE}/objects/zydyxx/versions/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "1"
        assert len(data["metrics"]) == 2
        assert data["snapshot"]["name"] == "住院待遇"
        assert {m["metric_code"] for m in data["metrics"]} == {
            "zydyxx.bcqfje", "zydyxx.bcybnje"}

    def test_object_detail_has_current_version(self, api_client):
        client, reg = api_client
        reg.publish_object("zydyxx")
        resp = client.get(f"{self._BASE}/objects/zydyxx")
        assert resp.status_code == 200
        body = resp.json()
        assert body["current_version"] == "1"
        assert body["status"] == "published"

    def test_object_list_shows_current_version(self, api_client):
        """未发布对象 current_version=None，已发布的显示版本号。"""
        client, reg = api_client
        reg.publish_object("zydyxx")
        resp = client.get(f"{self._BASE}/objects")
        by_code = {o["object_code"]: o for o in resp.json()}
        assert by_code["zydyxx"]["current_version"] == "1"
        assert by_code["djxx"]["current_version"] is None
