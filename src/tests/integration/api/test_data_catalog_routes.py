"""数据目录 API 集成测试（Issue #38 Slice 3）。

通过 create_app() 新建应用并覆盖存储依赖为内存实现，不连接真实外部资源。
refresh/sla 端点的真实源访问通过 monkeypatch 隔离，验证降级路径与契约。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.data_platform.storage.data_catalog.data_catalog_in_memory import (
    InMemoryDataCatalogStorage,
)
from src.domain.data_catalog.models import CatalogAsset, CatalogAssetType
from src.runtime.api import data_catalog_routes
from src.runtime.api.app import create_app
from src.runtime.api.data_catalog_routes import get_data_catalog_store

PREFIX = "/api/v1/medical-insurance-ai-agent/data-catalog"


@pytest.fixture()
def store() -> InMemoryDataCatalogStorage:
    return InMemoryDataCatalogStorage()


@pytest.fixture()
def client(store: InMemoryDataCatalogStorage) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_data_catalog_store] = lambda: store
    return TestClient(app)


def _seed(store: InMemoryDataCatalogStorage) -> CatalogAsset:
    asset = CatalogAsset(
        asset_id="ca_test001",
        asset_type=CatalogAssetType.METRIC,
        asset_key="metric:mzjyxx.T_FundPay",
        name="统筹基金支付",
        description="门诊统筹基金支付金额",
        owner="医保办",
        semantic_object_code="mzjyxx",
        semantic_version="4",
    )
    return store.upsert_asset(asset)


class TestAssets:
    def test_list_empty(self, client: TestClient) -> None:
        body = client.get(f"{PREFIX}/assets").json()
        assert body == {"items": [], "limit": 50, "offset": 0}

    def test_list_with_type_and_keyword(
        self, client: TestClient, store: InMemoryDataCatalogStorage
    ) -> None:
        _seed(store)
        store.upsert_asset(
            CatalogAsset(
                asset_id="ca_test002",
                asset_type=CatalogAssetType.SOURCE_TABLE,
                asset_key="source_table:mz_trade",
                name="门诊交易表",
            )
        )
        metrics = client.get(
            f"{PREFIX}/assets", params={"asset_type": "metric"}
        ).json()
        assert len(metrics["items"]) == 1
        assert metrics["items"][0]["asset_key"] == "metric:mzjyxx.T_FundPay"

        hit = client.get(f"{PREFIX}/assets", params={"keyword": "统筹"}).json()
        assert len(hit["items"]) == 1
        miss = client.get(f"{PREFIX}/assets", params={"keyword": "不存在"}).json()
        assert miss["items"] == []

    def test_get_detail_with_traceability(
        self, client: TestClient, store: InMemoryDataCatalogStorage
    ) -> None:
        seeded = _seed(store)
        response = client.get(f"{PREFIX}/assets/{seeded.asset_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["semantic_version"] == "4"
        assert body["owner"] == "医保办"

    def test_get_missing_404(self, client: TestClient) -> None:
        response = client.get(f"{PREFIX}/assets/ca_missing")
        assert response.status_code == 404
        assert response.json()["detail"]["error_code"] == "CATALOG_ASSET_NOT_FOUND"


class TestRefresh:
    def test_refresh_returns_stats(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """refresh 走构建器编排；真实源用 monkeypatch 隔离，验证契约与依赖注入。"""
        captured: dict[str, object] = {}

        def fake_refresh(storage: object) -> dict[str, int]:
            captured["storage"] = storage
            return {"upserted": 3, "pruned": 1}

        monkeypatch.setattr(
            "src.runtime.data_catalog.builder.refresh_data_catalog", fake_refresh
        )
        response = client.post(f"{PREFIX}/refresh")
        assert response.status_code == 200
        assert response.json() == {"upserted": 3, "pruned": 1}
        # 构建器拿到的必须是依赖注入覆盖的内存存储
        assert isinstance(captured["storage"], InMemoryDataCatalogStorage)


class TestLineage:
    def test_lineage_subgraph(
        self, client: TestClient, store: InMemoryDataCatalogStorage
    ) -> None:
        seeded = _seed(store)
        store.upsert_asset(
            CatalogAsset(
                asset_id="ca_obj001",
                asset_type=CatalogAssetType.SEMANTIC_OBJECT,
                asset_key="semantic_object:mzjyxx",
                name="门诊交易信息",
            )
        )
        body = client.get(f"{PREFIX}/assets/{seeded.asset_id}/lineage").json()
        assert body["root"] == seeded.asset_id
        ids = {n["asset_id"] for n in body["nodes"]}
        assert ids == {seeded.asset_id, "ca_obj001"}
        assert body["edges"][0]["relation"] == "belongs_to"

    def test_lineage_missing_404(self, client: TestClient) -> None:
        response = client.get(f"{PREFIX}/assets/ca_missing/lineage")
        assert response.status_code == 404
        assert response.json()["detail"]["error_code"] == "CATALOG_ASSET_NOT_FOUND"


class TestSla:
    def test_sla_degrades_independently(self, client: TestClient) -> None:
        """两数据源各自降级：真实源不可用时 outpatient_sync=None、quality_gates=[]。"""
        response = client.get(f"{PREFIX}/sla")
        assert response.status_code == 200
        body = response.json()
        assert "outpatient_sync" in body
        assert "quality_gates" in body
        assert isinstance(body["quality_gates"], list)

    def test_sla_populated(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import datetime, timezone

        from src.data_platform.storage.postgresql.outpatient_store import (
            OutpatientSyncStatus,
        )

        sync = OutpatientSyncStatus(
            source_id="bjybdb",
            last_batch_id="batch-1",
            last_mode=None,
            checkpoint_kind=None,
            checkpoint_value=None,
            last_published_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            last_non_empty_latency_seconds=None,
            non_empty_sample_count=10,
            p95_latency_seconds=123.4,
            quality_status="ok",
            semantic_version=None,
        )

        class _FakeOutpatientStore:
            def get_sync_status(self, source_id: str) -> OutpatientSyncStatus:
                assert source_id == "bjybdb"
                return sync

        class _FakePolicyMetaStore:
            def list_tasks(self, status: str = "", metric_code: str = "", limit: int = 50):
                return [
                    {
                        "task_id": "task_1",
                        "metric_code": "mzjyxx.T_FundPay",
                        "status": "completed",
                        "golden_score": {"filling_rate": 0.9},
                        "created_at": None,
                    }
                ]

        monkeypatch.setattr(
            "src.data_platform.storage.postgresql.outpatient_store.OutpatientPostgresStore",
            _FakeOutpatientStore,
        )
        monkeypatch.setattr(
            "src.data_platform.storage.postgresql.policy_meta_store.PolicyMetaStore",
            _FakePolicyMetaStore,
        )
        body = client.get(f"{PREFIX}/sla").json()
        assert body["outpatient_sync"]["last_batch_id"] == "batch-1"
        assert body["outpatient_sync"]["p95_latency_seconds"] == 123.4
        assert body["outpatient_sync"]["quality_status"] == "ok"
        assert body["quality_gates"][0]["golden_score"] == {"filling_rate": 0.9}
