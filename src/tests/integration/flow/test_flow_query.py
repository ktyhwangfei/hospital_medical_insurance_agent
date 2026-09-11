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

import base64
import hashlib
import hmac
import json
import time

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
JWT_SECRET = "flow-query-test-secret"

# #62 验收③ 四值口径（与 processed-snapshot 同源数值）
GOLDEN_ROW = {
    "op_valid_settle_count": 12,
    "op_total_fee": 6643.69,
    "op_fund_pay": 6530.03,
    "op_self_pay": 113.66,
}


def _auth_headers(
    role: str, permissions: list[str] | None = None,
) -> dict[str, str]:
    def encode(value: object) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":")).encode()
        ).decode().rstrip("=")

    header = encode({"alg": "HS256", "typ": "JWT"})
    payload = encode({
        "sub": f"{role}-user",
        "exp": time.time() + 3600,
        "roles": [role],
        "permissions": ["flow:read"] if permissions is None else permissions,
    })
    signing_input = f"{header}.{payload}"
    signature = base64.urlsafe_b64encode(
        hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return {"Authorization": f"Bearer {signing_input}.{signature}"}


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
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    registry = SemanticRegistry(store)
    monkeypatch.setattr(
        "src.semantic_layer.registry.get_semantic_registry",
        lambda: registry,
    )
    flow_storage = InMemoryGovernedFlowStorage()
    reader = StubReader([GOLDEN_ROW])
    query_service = FlowQueryService(flow_storage, reader)
    # 依赖注入必须复用同一服务实例（项目既有陷阱）
    govern_service = FlowGovernanceService(flow_storage)
    app = create_app()
    app.dependency_overrides[get_flow_service] = lambda: govern_service
    app.dependency_overrides[get_flow_query_service] = lambda: query_service
    api = TestClient(
        app,
        raise_server_exceptions=False,
        headers=_auth_headers("cashier"),
    )
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


def test_query_requires_flow_read_permission(parts):
    api, _, _ = parts
    response = api.post(
        f"{BASE}/{FLOW_ID}/query",
        json={},
        headers=_auth_headers("cashier", permissions=[]),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "AUTH_FORBIDDEN"


def test_query_requires_signed_token(parts):
    api, _, _ = parts
    response = api.post(
        f"{BASE}/{FLOW_ID}/query",
        json={},
        headers={"Authorization": ""},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "AUTH_REQUIRED"


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


# ── 指标码驱动消费（query_planner/问数层接入点）：POST /flow/consume ──────


def test_consume_by_metrics_resolves_published_contract(parts):
    """指标码全量消费：解析到已发布消费契约，走既有 T8/白名单/门禁链路。"""
    api, _, reader = parts
    _publish_golden(api)

    resp = api.post(f"{BASE}/consume", json={
        "metrics": [
            "mzjyxx.op_valid_settle_count", "mzjyxx.op_total_fee",
            "mzjyxx.op_fund_pay", "mzjyxx.op_self_pay",
        ],
    })
    assert resp.status_code == 200
    body = resp.json()
    # 契约声明用短码，指标码驱动侧以对象域全码解析
    assert body["flow_id"] == FLOW_ID
    assert body["rows"] == [GOLDEN_ROW]
    assert body["quality_status"] == "passed"
    assert reader.queries[-1][0] == "v_flow_flow_op_outpatient_processed"


def test_consume_by_metrics_subset_projects(parts):
    api, _, reader = parts
    _publish_golden(api)

    resp = api.post(f"{BASE}/consume", json={"metrics": ["mzjyxx.op_total_fee"]})
    assert resp.status_code == 200
    assert resp.json()["rows"] == [{"op_total_fee": 6643.69}]
    assert reader.queries[-1][1][0] == "op_total_fee"


def test_consume_by_metrics_no_contract_rejected(parts):
    """没有任何已发布消费契约覆盖请求指标 → 422 fail closed。"""
    api, _, reader = parts
    _publish_golden(api)

    resp = api.post(f"{BASE}/consume", json={"metrics": ["mzjyxx.op_avg_fee"]})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "FLOW_CONSUMES_UNKNOWN_METRIC"
    assert reader.queries == []


def test_consume_by_metrics_unpublished_flow_ignored(parts):
    """仅 pending_review 的 flow 不构成可解析契约（发布前不可消费）。"""
    api, _, reader = parts
    api.post(BASE, json=build_golden_flow().model_dump(mode="json"))
    api.post(f"{BASE}/{FLOW_ID}/submit-review")

    resp = api.post(f"{BASE}/consume", json={"metrics": ["mzjyxx.op_total_fee"]})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "FLOW_CONSUMES_UNKNOWN_METRIC"
    assert reader.queries == []


def test_consume_by_metrics_ambiguous_contract_rejected(parts):
    """多个已发布契约覆盖同一组指标 → 409 拒绝猜测（fail closed）。"""
    api, _, reader = parts
    _publish_golden(api)
    second = build_golden_flow().model_copy(update={"flow_id": "flow_op_dup"})
    api.post(BASE, json=second.model_dump(mode="json"))
    api.post(f"{BASE}/flow_op_dup/submit-review")
    assert api.post(
        f"{BASE}/flow_op_dup/publish", json={"published_by": "医保数据组"}
    ).status_code == 201

    resp = api.post(f"{BASE}/consume", json={"metrics": ["mzjyxx.op_total_fee"]})
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "FLOW_CONSUME_AMBIGUOUS"
    assert reader.queries == []


def test_consume_by_metrics_empty_request_rejected(parts):
    api, _, reader = parts
    _publish_golden(api)

    resp = api.post(f"{BASE}/consume", json={})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "FLOW_CONSUMES_UNKNOWN_METRIC"
    assert reader.queries == []


# ── T11 消费侧强制：permission_level × 调用方角色 ──────────────────────


def _publish_with_dimension(api, permission_level: str) -> None:
    """发布一个绑定 T_CureType 维度（指定权限级别）的 golden flow。"""
    from src.domain.governed_flow.models import (
        DimensionBinding,
        DimensionNode,
    )

    flow = build_golden_flow()
    flow.nodes.append(DimensionNode(
        node_id="dim_cure", name="门诊医疗类别维度",
        dimensions=[DimensionBinding(
            field_code="T_CureType", value_domain="MZ_CURE_TYPE",
            permission_level=permission_level,
        )],
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


@pytest.mark.parametrize("caller_role", [None, "cashier", "clinician", "intern"])
def test_query_detail_dimension_denied_for_summary_callers(parts, caller_role):
    """T11 消费侧强制：detail 级维度对 summary 调用方拒止（缺省/未知角色按 summary 收紧）。"""
    api, _, reader = parts
    _publish_with_dimension(api, "detail")
    payload: dict = {"metrics": ["op_total_fee"], "dimensions": ["T_CureType"]}
    headers = _auth_headers(caller_role) if caller_role else _auth_headers("cashier")

    resp = api.post(f"{BASE}/{FLOW_ID}/query", json=payload, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "FLOW_CONSUME_DIMENSION_PERMISSION_DENIED"
    assert reader.queries == []  # 拒止时不触达视图


def test_query_ignores_client_supplied_caller_role(parts):
    """请求体不能伪造 detail 角色提升权限。"""
    api, _, reader = parts
    _publish_with_dimension(api, "detail")

    resp = api.post(f"{BASE}/{FLOW_ID}/query", json={
        "metrics": ["op_total_fee"],
        "dimensions": ["T_CureType"],
        "caller_role": "information_department",
    })
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "FLOW_CONSUME_DIMENSION_PERMISSION_DENIED"
    assert reader.queries == []


@pytest.mark.parametrize("caller_role", ["information_department", "medical_office"])
def test_query_detail_dimension_allowed_for_detail_callers(parts, caller_role):
    """detail 级调用方（信息科/医保办）可下钻 detail 级维度。"""
    api, _, reader = parts
    _publish_with_dimension(api, "detail")
    reader.rows = [
        {"T_CureType": "11", "op_total_fee": 5000.0, "op_fund_pay": 4900.0, "op_self_pay": 100.0},
    ]

    resp = api.post(f"{BASE}/{FLOW_ID}/query", json={
        "metrics": ["op_total_fee"], "dimensions": ["T_CureType"],
    }, headers=_auth_headers(caller_role))
    assert resp.status_code == 200
    assert [r["T_CureType"] for r in resp.json()["rows"]] == ["11"]


def test_query_summary_dimension_open_to_any_caller(parts):
    """summary 级维度绑定不因调用方角色收紧（T11 只约束 detail 下钻）。"""
    api, _, reader = parts
    _publish_with_dimension(api, "summary")
    reader.rows = [
        {"T_CureType": "11", "op_total_fee": 5000.0, "op_fund_pay": 4900.0, "op_self_pay": 100.0},
    ]

    resp = api.post(f"{BASE}/{FLOW_ID}/query", json={
        "metrics": ["op_total_fee"], "dimensions": ["T_CureType"],
    })
    assert resp.status_code == 200
    assert reader.queries[-1][0] == "v_flow_flow_op_outpatient_processed"


def test_consume_by_metrics_enforces_dimension_permission(parts):
    """指标码驱动消费同链路强制：cashier 422，information_department 200。"""
    api, _, reader = parts
    _publish_with_dimension(api, "detail")
    reader.rows = [
        {"T_CureType": "11", "op_total_fee": 5000.0, "op_fund_pay": 4900.0, "op_self_pay": 100.0},
    ]

    denied = api.post(f"{BASE}/consume", json={
        "metrics": ["mzjyxx.op_total_fee"], "dimensions": ["T_CureType"],
    })
    assert denied.status_code == 422
    assert denied.json()["detail"]["error_code"] == "FLOW_CONSUME_DIMENSION_PERMISSION_DENIED"
    assert reader.queries == []

    allowed = api.post(f"{BASE}/consume", json={
        "metrics": ["mzjyxx.op_total_fee"], "dimensions": ["T_CureType"],
    }, headers=_auth_headers("information_department"))
    assert allowed.status_code == 200
    assert [r["T_CureType"] for r in allowed.json()["rows"]] == ["11"]
