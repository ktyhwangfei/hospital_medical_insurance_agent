"""治理 Flow API 测试（T2a）— Phase 1。

依赖注入内存存储 + 种子语义层（含 #62 四指标口径句 v4 与 mz_trade 落地数据集），
覆盖 12 个端点的 happy path 与 404/409/422 拒止路径。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.data_platform.storage.flow.flow_in_memory import InMemoryGovernedFlowStorage
from src.runtime.api.app import create_app
from src.runtime.api.flow_routes import get_flow_service
from src.runtime.flow.flow_service import FlowGovernanceService
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer
from src.tests.unit.governed_flow.golden_flow import build_golden_flow

BASE = "/api/v1/medical-insurance-ai-agent/flow"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", "governed-flow-test-secret")
    # 种子语义层：mz_trade 落地数据集 + mzjyxx.op_* 四指标（口径句 v4 已签核）
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    monkeypatch.setattr(
        "src.semantic_layer.registry.get_semantic_registry",
        lambda: SemanticRegistry(store),
    )
    # 依赖注入必须复用同一服务实例：lambda 内 new 存储会让每个请求拿到空库
    service = FlowGovernanceService(InMemoryGovernedFlowStorage())
    app = create_app()
    app.dependency_overrides[get_flow_service] = lambda: service
    return TestClient(app, raise_server_exceptions=False)


def _golden_payload() -> dict:
    return build_golden_flow().model_dump(mode="json")


class TestCrud:
    def test_create_returns_201_draft_with_hash(self, api):
        resp = api.post(BASE, json=_golden_payload())
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "draft"
        assert body["revision"] == 1
        assert len(body["content_hash"]) == 64

    def test_create_duplicate_409(self, api):
        api.post(BASE, json=_golden_payload())
        resp = api.post(BASE, json=_golden_payload())
        assert resp.status_code == 409
        assert resp.json()["detail"]["error_code"] == "FLOW_REVISION_CONFLICT"

    def test_get_missing_404(self, api):
        resp = api.get(f"{BASE}/nope")
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "FLOW_NOT_FOUND"

    def test_list_and_get(self, api):
        api.post(BASE, json=_golden_payload())
        assert len(api.get(BASE).json()) == 1
        detail = api.get(f"{BASE}/flow_op_outpatient_processed")
        assert detail.status_code == 200
        assert detail.json()["name"].startswith("门诊有效结算")

    def test_update_stale_revision_409(self, api):
        api.post(BASE, json=_golden_payload())
        resp = api.put(
            f"{BASE}/flow_op_outpatient_processed?expected_revision=99",
            json=_golden_payload(),
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["error_code"] == "FLOW_REVISION_CONFLICT"

    def test_update_bumps_revision(self, api):
        api.post(BASE, json=_golden_payload())
        payload = _golden_payload()
        payload["name"] = "门诊有效结算加工视图（改名）"
        resp = api.put(
            f"{BASE}/flow_op_outpatient_processed?expected_revision=1", json=payload
        )
        assert resp.status_code == 200
        assert resp.json()["revision"] == 2

    def test_delete_draft(self, api):
        api.post(BASE, json=_golden_payload())
        resp = api.delete(f"{BASE}/flow_op_outpatient_processed?expected_revision=1")
        assert resp.status_code == 200
        assert api.get(f"{BASE}/flow_op_outpatient_processed").status_code == 404


class TestValidateAndReview:
    def test_validate_golden_clean_with_seeded_context(self, api):
        api.post(BASE, json=_golden_payload())
        resp = api.post(f"{BASE}/flow_op_outpatient_processed/validate")
        assert resp.status_code == 200
        body = resp.json()
        assert body["issues"] == []
        assert body["has_blocking"] is False

    def test_validate_reports_unsigned_dataset(self, api):
        payload = _golden_payload()
        payload["nodes"][0]["dataset_code"] = "not_registered"
        payload["source_contracts"][0]["dataset_code"] = "not_registered"
        api.post(BASE, json=payload)
        resp = api.post(f"{BASE}/flow_op_outpatient_processed/validate")
        assert resp.status_code == 200
        codes = {i["code"] for i in resp.json()["issues"]}
        assert "FLOW_DATASET_NOT_REGISTERED" in codes

    def test_submit_review_then_publish_blocked_rejects(self, api):
        """口径句被篡改：过结构校验与评审，发布门禁 fail closed（422 带报告）。"""
        payload = _golden_payload()
        payload["metric_outputs"][0]["policy_definition"] += " AND 1=1"
        api.post(BASE, json=payload)
        assert api.post(f"{BASE}/flow_op_outpatient_processed/submit-review").status_code == 200
        resp = api.post(
            f"{BASE}/flow_op_outpatient_processed/publish",
            json={"published_by": "reviewer"},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error_code"] == "FLOW_CALIBER_NOT_SIGNED"
        assert detail["audit_event"]["issues"]  # 完整校验报告随响应返回

    def test_submit_review_only_from_draft(self, api):
        api.post(BASE, json=_golden_payload())
        api.post(f"{BASE}/flow_op_outpatient_processed/submit-review")
        resp = api.post(f"{BASE}/flow_op_outpatient_processed/submit-review")
        assert resp.status_code == 409
        assert resp.json()["detail"]["error_code"] == "FLOW_STATE_INVALID"


class TestPublish:
    def test_publish_golden_creates_active_evidence(self, api):
        api.post(BASE, json=_golden_payload())
        api.post(f"{BASE}/flow_op_outpatient_processed/submit-review")
        resp = api.post(
            f"{BASE}/flow_op_outpatient_processed/publish",
            json={"published_by": "医保数据组"},
        )
        assert resp.status_code == 201
        evidence = resp.json()
        assert evidence["revision_id"] == "flow_op_outpatient_processed-rev2"
        assert len(evidence["artifact_hash"]) == 64
        assert len(evidence["semantic_revision"]) == 64
        assert evidence["published_by"] == "医保数据组"
        # 主表翻转为 published
        flow = api.get(f"{BASE}/flow_op_outpatient_processed").json()
        assert flow["status"] == "published"
        assert flow["published_by"] == "医保数据组"

    def test_publish_only_from_pending_review(self, api):
        api.post(BASE, json=_golden_payload())
        resp = api.post(
            f"{BASE}/flow_op_outpatient_processed/publish",
            json={"published_by": "reviewer"},
        )
        assert resp.status_code == 409

    def test_revisions_list_marks_active(self, api):
        api.post(BASE, json=_golden_payload())
        api.post(f"{BASE}/flow_op_outpatient_processed/submit-review")
        api.post(f"{BASE}/flow_op_outpatient_processed/publish", json={"published_by": "r"})
        revisions = api.get(f"{BASE}/flow_op_outpatient_processed/revisions").json()
        assert len(revisions) == 1
        assert revisions[0]["is_active"] is True

    def test_preview_compiles_with_registry_resolver(self, api):
        api.post(BASE, json=_golden_payload())
        resp = api.get(f"{BASE}/flow_op_outpatient_processed/preview")
        assert resp.status_code == 200
        artifact = resp.json()
        assert 'FROM "public"."mz_trade"' in artifact["view_sql"]
        assert '("T_CureType" IN (11, 17, 18, 19) OR "T_CureType" IS NULL)' in artifact["view_sql"]
        assert len(artifact["query_plan"]) == 4

    def test_delete_published_rejected(self, api):
        api.post(BASE, json=_golden_payload())
        api.post(f"{BASE}/flow_op_outpatient_processed/submit-review")
        api.post(f"{BASE}/flow_op_outpatient_processed/publish", json={"published_by": "r"})
        flow = api.get(f"{BASE}/flow_op_outpatient_processed").json()
        resp = api.delete(
            f"{BASE}/flow_op_outpatient_processed?expected_revision={flow['revision']}"
        )
        assert resp.status_code == 409
