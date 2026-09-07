"""P3c 受控问数消费契约 — POST /flow/{flow_id}/query（先红后绿）。

消费纪律（issue #65 验收）：
- 仅 published + 活跃发布版本可消费；消费前重编译验 artifact_hash（T8）；
- 请求指标 ⊆ consumer.consumes 白名单（FLOW_CONSUMES_UNKNOWN_METRIC 拒止）；
- 请求维度 ⊆ 维度节点绑定白名单（T11 越权拒止 FLOW_CONSUME_DIMENSION_FORBIDDEN）；
- 勾稽恒等门禁在结果行上运行时评估：失败 → 200 + quality_status=unavailable +
  数值扣发（fail closed，不是报错）；
- 返回携带发布证据（revision_id / flow_revision / artifact_hash / view_name）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.data_platform.storage.flow.flow_in_memory import InMemoryGovernedFlowStorage
from src.runtime.api.app import create_app
from src.runtime.api.flow_routes import get_flow_query_service, get_flow_service
from src.runtime.flow.flow_query_service import FlowQueryService
from src.runtime.flow.flow_service import FlowGovernanceService
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer
from src.tests.unit.governed_flow.golden_flow import build_golden_flow

BASE = "/api/v1/medical-insurance-ai-agent/flow"
FLOW_ID = "flow_op_outpatient_processed"

# #62 验收③ 四值口径（与 processed-snapshot 同源数值）
GOLDEN_ROW = {
    "op_valid_settle_count": 12,
    "op_total_fee": 6643.69,
    "op_fund_pay": 6530.03,
    "op_self_pay": 113.66,
}


class StubReader:
    """按请求列投影的视图读取 stub；记录 (view_name, columns) 供断言。"""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.queries: list[tuple[str, list[str]]] = []

    def read(self, view_name: str, columns: list[str]) -> list[dict]:
        self.queries.append((view_name, list(columns)))
        return [{c: row.get(c) for c in columns} for row in self.rows]


@pytest.fixture
def parts(monkeypatch):
    """(api, storage, reader)：内存存储 + 种子语义层 + stub 读取器。"""
    monkeypatch.setenv("AUTH_JWT_SECRET", "flow-query-test-secret")
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    monkeypatch.setattr(
        "src.semantic_layer.registry.get_semantic_registry",
        lambda: SemanticRegistry(store),
    )
    flow_storage = InMemoryGovernedFlowStorage()
    reader = StubReader([GOLDEN_ROW])
    query_service = FlowQueryService(flow_storage, reader)
    # 依赖注入必须复用同一服务实例（项目既有陷阱）
    govern_service = FlowGovernanceService(flow_storage)
    app = create_app()
    app.dependency_overrides[get_flow_service] = lambda: govern_service
    app.dependency_overrides[get_flow_query_service] = lambda: query_service
    api = TestClient(app, raise_server_exceptions=False)
    return api, flow_storage, reader


def _publish_golden(api) -> dict:
    api.post(BASE, json=build_golden_flow().model_dump(mode="json"))
    api.post(f"{BASE}/{FLOW_ID}/submit-review")
    resp = api.post(f"{BASE}/{FLOW_ID}/publish", json={"published_by": "医保数据组"})
    assert resp.status_code == 201
    return resp.json()


def test_query_default_returns_all_consumed_metrics_with_evidence(parts):
    api, _, reader = parts
    revision = _publish_golden(api)

    resp = api.post(f"{BASE}/{FLOW_ID}/query", json={})
    assert resp.status_code == 200
    body = resp.json()
    # 消费契约四字段全量（consumer.consumes 白名单）
    assert reader.queries == [(
        "v_flow_flow_op_outpatient_processed",
        ["op_valid_settle_count", "op_total_fee", "op_fund_pay", "op_self_pay"],
    )]
    assert body["rows"] == [GOLDEN_ROW]
    assert body["quality_status"] == "passed"
    assert body["metrics"] == [
        "op_valid_settle_count", "op_total_fee", "op_fund_pay", "op_self_pay",
    ]
    assert body["dimensions"] == []
    # 发布证据回带（来源可追溯）
    assert body["revision_id"] == revision["revision_id"]
    assert body["flow_revision"] == revision["flow_revision"]
    assert body["artifact_hash"] == revision["artifact_hash"]
    assert body["view_name"] == "v_flow_flow_op_outpatient_processed"
    assert body["published_by"] == "医保数据组"


def test_query_metric_subset_projects_requested_columns(parts):
    api, _, reader = parts
    _publish_golden(api)

    resp = api.post(f"{BASE}/{FLOW_ID}/query", json={"metrics": ["op_total_fee"]})
    assert resp.status_code == 200
    # 门禁列随请求一并读取（全口径勾稽），出参投影回请求列
    assert reader.queries[-1][1] == ["op_total_fee", "op_fund_pay", "op_self_pay"]
    assert resp.json()["rows"] == [{"op_total_fee": 6643.69}]


def test_query_unknown_metric_rejected(parts):
    api, _, reader = parts
    _publish_golden(api)

    resp = api.post(f"{BASE}/{FLOW_ID}/query", json={"metrics": ["not_a_metric"]})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "FLOW_CONSUMES_UNKNOWN_METRIC"
    assert reader.queries == []  # 拒止时不触达视图


def test_query_dimension_without_binding_forbidden(parts):
    """T11：golden flow 未绑定维度，下钻请求必须拒止。"""
    api, _, reader = parts
    _publish_golden(api)

    resp = api.post(
        f"{BASE}/{FLOW_ID}/query",
        json={"metrics": ["op_total_fee"], "dimensions": ["T_CureType"]},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "FLOW_CONSUME_DIMENSION_FORBIDDEN"
    assert reader.queries == []


def test_query_dimension_allowed_when_bound(parts):
    """绑定维度节点的 flow 可按声明维度下钻（列随维度扩展）。"""
    api, flow_storage, reader = parts
    flow = build_golden_flow()
    from src.domain.governed_flow.models import (
        DimensionBinding,
        DimensionNode,
    )
    flow.nodes.append(DimensionNode(
        node_id="dim_cure", name="门诊医疗类别维度",
        dimensions=[DimensionBinding(field_code="T_CureType", value_domain="MZ_CURE_TYPE")],
    ))
    flow.edges = [
        e.model_copy(update={"to_node": "dim_cure"}) if e.edge_id == "e3" else e
        for e in flow.edges
    ]
    flow.edges.append(
        type(flow.edges[0])(edge_id="e_dim", from_node="dim_cure", to_node="gate_caliber")
    )
    api.post(BASE, json=flow.model_dump(mode="json"))
    api.post(f"{BASE}/{FLOW_ID}/submit-review")
    assert api.post(
        f"{BASE}/{FLOW_ID}/publish", json={"published_by": "医保数据组"}
    ).status_code == 201

    reader.rows = [
        {"T_CureType": "11", "op_total_fee": 5000.0, "op_fund_pay": 4900.0, "op_self_pay": 100.0},
        {"T_CureType": "17", "op_total_fee": 1643.69, "op_fund_pay": 1630.03, "op_self_pay": 13.66},
    ]
    resp = api.post(
        f"{BASE}/{FLOW_ID}/query",
        json={"metrics": ["op_total_fee"], "dimensions": ["T_CureType"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert reader.queries[-1] == (
        "v_flow_flow_op_outpatient_processed",
        ["op_total_fee", "T_CureType", "op_fund_pay", "op_self_pay"],
    )
    assert [r["T_CureType"] for r in body["rows"]] == ["11", "17"]
    assert body["quality_status"] == "passed"  # 逐行勾稽 5000=4900+100 …


def test_query_identity_gate_failure_withholds_values(parts):
    """勾稽恒等失败：200 + unavailable + 数值扣发（fail closed 不报错）。"""
    api, _, reader = parts
    _publish_golden(api)
    reader.rows = [{
        "op_valid_settle_count": 12,
        "op_total_fee": 6643.69,
        "op_fund_pay": 6500.00,   # 6500 + 113.66 != 6643.69
        "op_self_pay": 113.66,
    }]

    resp = api.post(f"{BASE}/{FLOW_ID}/query", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["quality_status"] == "unavailable"
    assert body["rows"] == []
    failed = [g for g in body["gate_results"] if not g["passed"]]
    assert failed, "门禁结果必须包含失败项及差异说明"
    assert failed[0]["check_type"] == "identity_assertion"
    assert "op_total_fee" in failed[0]["detail"]


def test_query_none_values_pass_identity(parts):
    """空数据集：视图单行全 NULL，按 0 参与勾稽 0=0+0 通过（口径不破）。"""
    api, _, reader = parts
    _publish_golden(api)
    reader.rows = [{
        "op_valid_settle_count": 0,
        "op_total_fee": None,
        "op_fund_pay": None,
        "op_self_pay": None,
    }]

    resp = api.post(f"{BASE}/{FLOW_ID}/query", json={})
    assert resp.status_code == 200
    assert resp.json()["quality_status"] == "passed"


def test_query_unpublished_flow_rejected(parts):
    api, _, reader = parts
    api.post(BASE, json=build_golden_flow().model_dump(mode="json"))
    api.post(f"{BASE}/{FLOW_ID}/submit-review")  # 停在 pending_review

    resp = api.post(f"{BASE}/{FLOW_ID}/query", json={})
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "FLOW_STATE_INVALID"
    assert reader.queries == []


def test_query_tampered_active_evidence_rejected(parts):
    """T8：存储中发布证据被篡改 → 重编译哈希不一致 → 409 拒止消费。"""
    api, flow_storage, reader = parts
    revision = _publish_golden(api)
    tampered = flow_storage.get_published_revision(revision["revision_id"])
    tampered.definition.nodes[1].conditions[0] = (
        tampered.definition.nodes[1].conditions[0].model_copy(update={"value": [9]})
    )
    flow_storage.save_published_revision(tampered)

    resp = api.post(f"{BASE}/{FLOW_ID}/query", json={})
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "FLOW_ARTIFACT_MISMATCH"
    assert reader.queries == []


def test_query_flow_not_found(parts):
    api, _, _ = parts
    resp = api.post(f"{BASE}/flow_missing/query", json={})
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "FLOW_NOT_FOUND"
