"""数据目录 API 集成测试 — issue #38：搜索/详情/血缘/SLA 端点契约。"""
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app
from src.runtime.api.catalog_routes import get_catalog_service
from src.tests.unit.runtime.test_catalog_service import _build_service, _default_reader

BASE = "/api/v1/medical-insurance-ai-agent/catalog"


def _api() -> TestClient:
    service = _build_service(_default_reader())
    app = create_app()
    app.dependency_overrides[get_catalog_service] = lambda: service
    return TestClient(app, raise_server_exceptions=False)


class TestSearch:
    def test_search_returns_hits_with_type_filter(self):
        api = _api()
        resp = api.get(f"{BASE}/search", params={"q": "自付金额", "asset_type": "metric"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "自付金额"
        assert body["total"] >= 1
        item = body["items"][0]
        assert item["asset_type"] == "metric"
        assert item["asset_id"] == "Settlement.cash_pay"
        assert item["title"] == "现金自付金额"

    def test_search_requires_query(self):
        api = _api()
        assert api.get(f"{BASE}/search", params={"q": ""}).status_code == 422
        assert api.get(f"{BASE}/search").status_code == 422

    def test_search_invalid_type_422(self):
        api = _api()
        assert api.get(
            f"{BASE}/search", params={"q": "结算", "asset_type": "bogus"}
        ).status_code == 422


class TestAssetAndLineage:
    def test_dataset_detail(self):
        api = _api()
        resp = api.get(f"{BASE}/assets/dataset/mz_trade")
        assert resp.status_code == 200
        body = resp.json()
        assert body["asset"]["asset_type"] == "dataset"
        assert len(body["fields"]) == 3
        assert len(body["batches"]) == 2
        assert [v["version"] for v in body["versions"]] == ["1"]

    def test_metric_detail_with_policy_carrier(self):
        api = _api()
        resp = api.get(f"{BASE}/assets/metric/Settlement.cash_pay")
        assert resp.status_code == 200
        summary = {kv["key"]: kv["value"] for kv in resp.json()["summary"]}
        assert summary["政策文号"] == "医保发〔2024〕1号"

    def test_unknown_asset_404(self):
        api = _api()
        for asset_type in ("dataset", "field", "object", "metric", "consumer"):
            resp = api.get(f"{BASE}/assets/{asset_type}/nope")
            assert resp.status_code == 404
            assert resp.json()["detail"]["error_code"] == "CATALOG_ASSET_NOT_FOUND"

    def test_lineage_chain(self):
        api = _api()
        resp = api.get(f"{BASE}/lineage/metric/Settlement.cash_pay")
        assert resp.status_code == 200
        body = resp.json()
        assert body["sources"] == ["outpatient_postgres"]
        assert [b["batch_id"] for b in body["batches"]] == ["b-new", "b-old"]
        assert [c["consumer_id"] for c in body["consumers"]] == ["demo_skill"]

    def test_lineage_unknown_404(self):
        api = _api()
        resp = api.get(f"{BASE}/lineage/object/nope")
        assert resp.status_code == 404

    def test_invalid_asset_type_422(self):
        api = _api()
        assert api.get(f"{BASE}/assets/bogus/x").status_code == 422
        assert api.get(f"{BASE}/lineage/bogus/x").status_code == 422


class TestSlaAndOverview:
    def test_sla_board_shape(self):
        api = _api()
        resp = api.get(f"{BASE}/sla")
        assert resp.status_code == 200
        body = resp.json()
        sla = body["sources"][0]
        assert sla["source_id"] == "bjybdb"
        assert sla["job_status"] == "ready"
        assert sla["last_batch"]["row_count"] == 12
        assert (sla["recent_runs_total"], sla["recent_runs_failed"]) == (3, 1)
        assert len(body["recent_batches"]) == 2

    def test_overview_counts(self):
        api = _api()
        body = api.get(f"{BASE}/overview").json()
        assert body["counts"]["metric"] == 2
        assert body["sla_sources"] == 1
