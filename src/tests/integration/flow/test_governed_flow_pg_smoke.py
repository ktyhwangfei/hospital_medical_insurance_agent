"""治理 Flow PG 存储活库冒烟 — Phase 1。

验证 governed_flows / governed_flow_revisions 双表 DDL、单活跃部分唯一索引
与活跃版本单条 UPDATE 原子切换在真实 PostgreSQL 上成立。
环境依赖: PostgreSQL（127.0.0.1:5432/hospital_mcp，与生产同构）；不可用时整组 skip。
"""
from __future__ import annotations

import pytest

from src.data_platform.storage.flow.flow_postgres import PostgresGovernedFlowStorage
from src.domain.governed_flow.models import FlowNotFoundError, FlowPublishedRevision
from src.tests.unit.governed_flow.golden_flow import build_golden_flow


def _pg_ready() -> bool:
    try:
        from src.data_platform.storage.postgresql.client import PostgreSQLClient

        client = PostgreSQLClient()
        client.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_ready(), reason="PostgreSQL 不可用，跳过活库冒烟")

FLOW_ID = "flow_pg_smoke_test"


@pytest.fixture
def storage() -> PostgresGovernedFlowStorage:
    return PostgresGovernedFlowStorage()


@pytest.fixture(autouse=True)
def _cleanup(storage: PostgresGovernedFlowStorage):
    yield
    client = storage._get_client()
    client.execute("DELETE FROM governed_flow_revisions WHERE flow_id = %s", (FLOW_ID,))
    client.execute("DELETE FROM governed_flows WHERE flow_id = %s", (FLOW_ID,))


def _published(flow, revision: int) -> FlowPublishedRevision:
    return FlowPublishedRevision(
        revision_id=f"{FLOW_ID}-rev{revision}",
        flow_id=FLOW_ID,
        flow_revision=revision,
        content_hash=flow.content_hash or "0" * 64,
        semantic_revision="s" * 64,
        artifact_hash=f"a{revision}" * 32,
        published_at="2026-09-04T00:00:00+00:00",
        published_by="pg-smoke",
        definition=flow.model_copy(deep=True),
    )


def test_pg_roundtrip_and_active_switch(storage: PostgresGovernedFlowStorage):
    flow = build_golden_flow().model_copy(update={"flow_id": FLOW_ID})
    flow.content_hash = flow.content_hash or ""

    # 主表 CRUD + JSONB 往返
    storage.create_flow(flow)
    loaded = storage.get_flow(FLOW_ID)
    assert loaded is not None and loaded.nodes[0].dataset_code == "o_trade"

    # 发布证据：后发版本自动置活跃（部分唯一索引保证单活跃）
    storage.save_published_revision(_published(flow, 1))
    storage.save_published_revision(_published(flow, 2))
    active = storage.get_active_revision(FLOW_ID)
    assert active is not None and active.flow_revision == 2
    revisions = storage.list_published_revisions(FLOW_ID)
    assert [r.flow_revision for r in revisions] == [1, 2]

    # 回滚：单条 UPDATE 原子切换，不产生新证据
    storage.set_active_revision(FLOW_ID, f"{FLOW_ID}-rev1")
    assert storage.get_active_revision(FLOW_ID).flow_revision == 1
    assert len(storage.list_published_revisions(FLOW_ID)) == 2

    # 跨 flow 切换拒绝
    with pytest.raises(FlowNotFoundError):
        storage.set_active_revision("other_flow", f"{FLOW_ID}-rev1")
