"""治理 Flow 内存存储单元测试 — Phase 1。"""
from __future__ import annotations

import pytest

from src.data_platform.storage.flow.flow_in_memory import InMemoryGovernedFlowStorage
from src.domain.governed_flow.models import (
    FlowDefinition,
    FlowNotFoundError,
    FlowPublishedRevision,
    FlowRevisionConflictError,
    compute_flow_content_hash,
)
from src.tests.unit.governed_flow.golden_flow import build_golden_flow


@pytest.fixture
def storage() -> InMemoryGovernedFlowStorage:
    return InMemoryGovernedFlowStorage()


@pytest.fixture
def saved_flow(storage: InMemoryGovernedFlowStorage) -> FlowDefinition:
    flow = build_golden_flow()
    flow.content_hash = compute_flow_content_hash(flow)
    return storage.create_flow(flow)


def _published(flow: FlowDefinition, revision: int = 1) -> FlowPublishedRevision:
    return FlowPublishedRevision(
        revision_id=f"{flow.flow_id}-rev{revision}",
        flow_id=flow.flow_id,
        flow_revision=revision,
        content_hash=flow.content_hash or "0" * 64,
        semantic_revision="s" * 64,
        artifact_hash="a" * 64,
        published_at="2026-09-04T00:00:00+00:00",
        published_by="reviewer",
        definition=flow.model_copy(deep=True),
    )


class TestFlowCrud:
    def test_create_and_get_roundtrip(self, storage, saved_flow):
        loaded = storage.get_flow(saved_flow.flow_id)
        assert loaded is not None and loaded.flow_id == saved_flow.flow_id
        assert loaded.nodes[0].node_id == "src_trade"

    def test_create_duplicate_conflicts(self, storage, saved_flow):
        with pytest.raises(FlowRevisionConflictError):
            storage.create_flow(build_golden_flow())

    def test_get_missing_returns_none(self, storage):
        assert storage.get_flow("nope") is None

    def test_update_with_matching_revision(self, storage, saved_flow):
        updated = saved_flow.model_copy(deep=True, update={
            "name": "改名", "revision": saved_flow.revision + 1,
        })
        result = storage.update_flow(updated, expected_revision=saved_flow.revision)
        assert result.name == "改名"
        assert storage.get_flow(saved_flow.flow_id).revision == 2

    def test_update_with_stale_revision_conflicts(self, storage, saved_flow):
        updated = saved_flow.model_copy(deep=True, update={"name": "改名", "revision": 99})
        with pytest.raises(FlowRevisionConflictError):
            storage.update_flow(updated, expected_revision=saved_flow.revision - 1)

    def test_update_missing_not_found(self, storage):
        flow = build_golden_flow()
        with pytest.raises(FlowNotFoundError):
            storage.update_flow(flow, expected_revision=1)

    def test_delete_with_matching_revision(self, storage, saved_flow):
        storage.delete_flow(saved_flow.flow_id, expected_revision=saved_flow.revision)
        assert storage.get_flow(saved_flow.flow_id) is None

    def test_delete_stale_revision_conflicts(self, storage, saved_flow):
        with pytest.raises(FlowRevisionConflictError):
            storage.delete_flow(saved_flow.flow_id, expected_revision=999)

    def test_storage_isolation_from_mutation(self, storage, saved_flow):
        """返回的副本被修改不得污染存储内部状态。"""
        loaded = storage.get_flow(saved_flow.flow_id)
        loaded.nodes[0].name = "被篡改"
        assert storage.get_flow(saved_flow.flow_id).nodes[0].name != "被篡改"


class TestPublishedRevisions:
    def test_save_activates_latest(self, storage, saved_flow):
        first = _published(saved_flow, revision=1)
        second = _published(saved_flow, revision=2)
        storage.save_published_revision(first)
        storage.save_published_revision(second)
        active = storage.get_active_revision(saved_flow.flow_id)
        assert active is not None and active.revision_id == second.revision_id

    def test_list_sorted_by_flow_revision(self, storage, saved_flow):
        storage.save_published_revision(_published(saved_flow, revision=2))
        storage.save_published_revision(_published(saved_flow, revision=1))
        revisions = storage.list_published_revisions(saved_flow.flow_id)
        assert [r.flow_revision for r in revisions] == [1, 2]

    def test_set_active_switches_pointer(self, storage, saved_flow):
        storage.save_published_revision(_published(saved_flow, revision=1))
        storage.save_published_revision(_published(saved_flow, revision=2))
        storage.set_active_revision(saved_flow.flow_id, f"{saved_flow.flow_id}-rev1")
        active = storage.get_active_revision(saved_flow.flow_id)
        assert active is not None and active.flow_revision == 1
        # 切换不产生新证据：版本清单不变
        assert len(storage.list_published_revisions(saved_flow.flow_id)) == 2

    def test_set_active_wrong_flow_not_found(self, storage, saved_flow):
        storage.save_published_revision(_published(saved_flow, revision=1))
        with pytest.raises(FlowNotFoundError):
            storage.set_active_revision("other_flow", f"{saved_flow.flow_id}-rev1")

    def test_get_active_without_publish_returns_none(self, storage, saved_flow):
        assert storage.get_active_revision(saved_flow.flow_id) is None
