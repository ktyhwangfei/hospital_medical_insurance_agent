"""治理 Flow 生命周期 Flow 测试（T2b）— Phase 1。

通过真实 app + 内存存储 + 种子语义层走完整闭环：
create → validate → submit-review → publish（fail closed 分支 + 正常分支）
→ 已发布再编辑开新修订 → 二次发布 → 回滚只切活跃版本 → deprecate 终态。
断言发布证据不可变、三锁（flow revision + semantic revision + artifact hash）齐全。
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
FLOW_ID = "flow_op_outpatient_processed"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", "governed-flow-flow-test-secret")
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


def test_full_lifecycle(api):
    # 1. 草稿创建 + 校验干净（真实签核上下文：mz_trade 已登记、口径句 v4 已签核）
    assert api.post(BASE, json=build_golden_flow().model_dump(mode="json")).status_code == 201
    report = api.post(f"{BASE}/{FLOW_ID}/validate").json()
    assert report["has_blocking"] is False

    # 2. 评审 → 发布：三锁齐全的活跃证据
    assert api.post(f"{BASE}/{FLOW_ID}/submit-review").status_code == 200
    first = api.post(f"{BASE}/{FLOW_ID}/publish", json={"published_by": "医保数据组"}).json()
    assert len(first["content_hash"]) == 64
    assert len(first["semantic_revision"]) == 64
    assert len(first["artifact_hash"]) == 64
    active_hash_r1 = first["content_hash"]

    # 3. 已发布再编辑 = 开新修订（活跃 rev1 证据不受影响）
    edited = build_golden_flow().model_dump(mode="json")
    edited["name"] = "门诊有效结算加工视图（v2 更名）"
    put = api.put(f"{BASE}/{FLOW_ID}?expected_revision=3", json=edited)
    assert put.status_code == 200
    assert put.json()["status"] == "draft"
    revisions = api.get(f"{BASE}/{FLOW_ID}/revisions").json()
    assert len(revisions) == 1 and revisions[0]["is_active"] is True

    # 4. 二次发布 → 双版本证据，新版本活跃
    api.post(f"{BASE}/{FLOW_ID}/submit-review")
    second = api.post(f"{BASE}/{FLOW_ID}/publish", json={"published_by": "医保数据组"}).json()
    revisions = api.get(f"{BASE}/{FLOW_ID}/revisions").json()
    assert len(revisions) == 2
    assert revisions[-1]["is_active"] is True and not revisions[0]["is_active"]

    # 5. 回滚只切活跃版本：不新增证据、主表回放 rev1 定义
    rollback = api.post(
        f"{BASE}/{FLOW_ID}/rollback", json={"revision_id": first["revision_id"]}
    )
    assert rollback.status_code == 200
    assert rollback.json()["is_active"] is True
    revisions = api.get(f"{BASE}/{FLOW_ID}/revisions").json()
    assert len(revisions) == 2  # 证据不可变：回滚不产生新版本
    assert revisions[0]["is_active"] is True
    flow = api.get(f"{BASE}/{FLOW_ID}").json()
    assert flow["status"] == "published"
    assert flow["content_hash"] == active_hash_r1  # 主表回放到 rev1 内容
    assert flow["name"].startswith("门诊有效结算加工视图（#62")  # rev1 原名

    # 6. 回滚到不属于本 flow 的版本 → 404
    resp = api.post(f"{BASE}/{FLOW_ID}/rollback", json={"revision_id": "alien-rev9"})
    assert resp.status_code == 404

    # 7. deprecate 终态：后续编辑/回滚/删除全部拒止
    assert api.post(f"{BASE}/{FLOW_ID}/deprecate").status_code == 200
    deprecated = api.get(f"{BASE}/{FLOW_ID}").json()
    assert deprecated["status"] == "deprecated"
    assert api.put(
        f"{BASE}/{FLOW_ID}?expected_revision={deprecated['revision']}",
        json=build_golden_flow().model_dump(mode="json"),
    ).status_code == 409
    assert api.post(
        f"{BASE}/{FLOW_ID}/rollback", json={"revision_id": first["revision_id"]}
    ).status_code == 409
    # 发布证据仍完整保留（终态不删历史）
    assert len(api.get(f"{BASE}/{FLOW_ID}/revisions").json()) == 2


def test_published_flow_preview_matches_view_sql(api):
    """发布后的预览产物与 #62 视图口径语义一致（服务级编译走注册表解析器）。"""
    api.post(BASE, json=build_golden_flow().model_dump(mode="json"))
    api.post(f"{BASE}/{FLOW_ID}/submit-review")
    api.post(f"{BASE}/{FLOW_ID}/publish", json={"published_by": "医保数据组"})
    artifact = api.get(f"{BASE}/{FLOW_ID}/preview").json()
    sql = artifact["view_sql"]
    assert 'COUNT(DISTINCT "T_TradeNo") AS "op_valid_settle_count"' in sql
    assert 'SUM("T_FeeAll") AS "op_total_fee"' in sql
    assert '"T_State" IN (2, 3)' in sql
    assert '"NP_Settle_State" = 1' in sql
    assert '"T_HasRefundmented" != 1' in sql
    assert '("T_PartialReturnFlag" IN (\'\') OR "T_PartialReturnFlag" IS NULL)' in sql
    assert '("T_CureType" IN (11, 17, 18, 19) OR "T_CureType" IS NULL)' in sql
