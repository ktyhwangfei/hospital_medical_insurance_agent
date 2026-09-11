"""P3b 发布部署视图 — 服务级行为测试（先红后绿）。

部署纪律（fail closed）：
- publish 先部署 DDL 再落发布证据：部署失败 → 无新版本、状态留在 pending_review；
- rollback 重编译目标定义校验 artifact_hash（T8 防篡改）后重部署，再切活跃指针；
- 发布证据定义被篡改 → FLOW_ARTIFACT_MISMATCH 拒绝回滚。
"""
from __future__ import annotations

import pytest

from src.data_platform.storage.flow.flow_in_memory import InMemoryGovernedFlowStorage
from src.domain.governed_flow.models import FlowArtifactMismatchError
from src.runtime.flow.flow_service import FlowGovernanceService
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer
from src.tests.unit.governed_flow.golden_flow import build_golden_flow

FLOW_ID = "flow_op_outpatient_processed"


class RecordingDeployer:
    """记录部署调用的 stub；fail=True 模拟 PG 不可用。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[str] = []
        self._fail = fail

    def deploy_view(self, view_sql: str) -> None:
        self.calls.append(view_sql)
        if self._fail:
            raise RuntimeError("pg unavailable")


@pytest.fixture
def registry(monkeypatch):
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    monkeypatch.setattr(
        "src.semantic_layer.registry.get_semantic_registry",
        lambda: SemanticRegistry(store),
    )


def _published_service() -> tuple[FlowGovernanceService, RecordingDeployer]:
    """golden flow 走完 create → submit-review → publish 的服务 + 记录部署器。"""
    deployer = RecordingDeployer()
    service = FlowGovernanceService(InMemoryGovernedFlowStorage(), deployer)
    service.create_flow(build_golden_flow())
    service.submit_review(FLOW_ID)
    return service, deployer


def test_publish_deploys_view_before_saving_revision(registry):
    service, deployer = _published_service()
    revision = service.publish_flow(FLOW_ID, published_by="医保数据组")

    assert len(deployer.calls) == 1
    sql = deployer.calls[0]
    assert sql.startswith("CREATE OR REPLACE VIEW v_flow_flow_op_outpatient_processed")
    # P3a 转型必须进部署产物（编译期转型，部署期不改写）
    assert "NULLIF(\"T_State\", '')::NUMERIC" in sql
    # 部署成功才落证据：活跃版本即本次产物哈希
    active = service.get_active_revision(FLOW_ID)
    assert active is not None and active.artifact_hash == revision.artifact_hash


def test_deploy_failure_leaves_no_revision(registry):
    deployer = RecordingDeployer(fail=True)
    service = FlowGovernanceService(InMemoryGovernedFlowStorage(), deployer)
    service.create_flow(build_golden_flow())
    service.submit_review(FLOW_ID)

    with pytest.raises(RuntimeError, match="pg unavailable"):
        service.publish_flow(FLOW_ID, published_by="医保数据组")

    # fail closed：无发布证据、无活跃版本、状态留在 pending_review
    assert service.list_revisions(FLOW_ID) == []
    assert service.get_active_revision(FLOW_ID) is None
    assert service.get_flow(FLOW_ID).status.value == "pending_review"


def test_rollback_redeploys_target_revision_sql(registry):
    service, deployer = _published_service()
    first = service.publish_flow(FLOW_ID, published_by="医保数据组")
    first_sql = deployer.calls[0]

    # 二次修订发布（改过滤条件 → 不同 artifact_hash 的第二版本）
    edited = build_golden_flow()
    edited.nodes[1].conditions[0] = edited.nodes[1].conditions[0].model_copy(
        update={"value": [2]}
    )
    service.update_flow(
        FLOW_ID, edited, expected_revision=service.get_flow(FLOW_ID).revision
    )
    service.submit_review(FLOW_ID)
    service.publish_flow(FLOW_ID, published_by="医保数据组")
    assert len(deployer.calls) == 2 and deployer.calls[1] != first_sql

    # 回滚到 rev1：重部署 rev1 的 DDL（与首次部署逐字一致）再切活跃
    service.rollback_flow(FLOW_ID, first.revision_id)
    assert len(deployer.calls) == 3
    assert deployer.calls[2] == first_sql
    active = service.get_active_revision(FLOW_ID)
    assert active is not None and active.revision_id == first.revision_id


def test_rollback_tampered_evidence_rejected(registry):
    service, deployer = _published_service()
    first = service.publish_flow(FLOW_ID, published_by="医保数据组")

    # 直接改存储中的发布证据定义（模拟库内篡改）：重编译产物哈希将不一致
    storage = service._storage
    tampered = storage.get_published_revision(first.revision_id)
    tampered.definition.nodes[1].conditions[0] = tampered.definition.nodes[1].conditions[0].model_copy(
        update={"value": [9]}
    )
    storage.save_published_revision(tampered)

    with pytest.raises(FlowArtifactMismatchError, match="FLOW_ARTIFACT_MISMATCH"):
        service.rollback_flow(FLOW_ID, first.revision_id)
    # 拒止时既不部署也不切活跃指针
    assert len(deployer.calls) == 1
    active = service.get_active_revision(FLOW_ID)
    assert active is not None and active.revision_id == first.revision_id
