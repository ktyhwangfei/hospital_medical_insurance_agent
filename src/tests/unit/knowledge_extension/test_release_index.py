from __future__ import annotations

import pytest

from src.knowledge_extension.rule_explanation.quality_models import KnowledgeRelease
from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore


class FakeIndexBackend:
    def __init__(self, healthy: bool = True) -> None:
        self.calls: list[tuple[str, str]] = []
        self.healthy = healthy

    def create(self, kind: str, collection_name: str) -> None:
        self.calls.append((f"create_{kind}", collection_name))

    def insert(self, kind: str, collection_name: str, records: list[dict]) -> None:
        self.calls.append((f"insert_{kind}", collection_name))

    def load(self, collection_name: str) -> None:
        self.calls.append(("load", collection_name))

    def is_healthy(self, collection_name: str) -> bool:
        self.calls.append(("health", collection_name))
        return self.healthy


def _building_release() -> KnowledgeRelease:
    return KnowledgeRelease(
        release_id="rel_20260803_01",
        status="building",
        facts_collection="policy_facts_rel_20260803_01",
        rules_collection="policy_rules_rel_20260803_01",
        contract_version="2",
        case_set_version=1,
        config_hash="cfg_1",
    )


def test_build_loads_and_checks_one_collection_pair_before_ready() -> None:
    from src.knowledge_extension.rule_explanation.release_index import ReleaseIndexBuilder

    store = InMemoryPolicyQualityStore()
    release = _building_release()
    store.save_release(release)
    backend = FakeIndexBackend()

    ready = ReleaseIndexBuilder(store, backend).build(
        release.release_id,
        facts=[{"fact_id": "fact_1"}],
        rules=[{"rule_id": "rule_1"}],
    )

    assert ready.status == "ready"
    assert backend.calls == [
        ("create_facts", release.facts_collection),
        ("create_rules", release.rules_collection),
        ("insert_facts", release.facts_collection),
        ("insert_rules", release.rules_collection),
        ("load", release.facts_collection),
        ("load", release.rules_collection),
        ("health", release.facts_collection),
        ("health", release.rules_collection),
    ]


def test_unhealthy_collection_pair_never_becomes_ready() -> None:
    from src.knowledge_extension.rule_explanation.release_index import ReleaseIndexBuilder

    store = InMemoryPolicyQualityStore()
    release = _building_release()
    store.save_release(release)

    with pytest.raises(RuntimeError, match="collection 对健康检查失败"):
        ReleaseIndexBuilder(store, FakeIndexBackend(healthy=False)).build(
            release.release_id, facts=[], rules=[]
        )

    assert store.get_release(release.release_id).status == "building"  # type: ignore[union-attr]


def test_workbench_content_source_preserves_stable_knowledge_id() -> None:
    from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
        ApprovedUnit,
        KnowledgeConfidence,
        KnowledgeItem,
        KnowledgeWorkbenchDocument,
        WorkbenchDocumentList,
        WorkbenchDocumentSummary,
    )
    from src.knowledge_extension.rule_explanation.release_index import (
        KnowledgeWorkbenchReleaseSource,
    )

    item = KnowledgeItem(
        knowledge_id="kn_stable",
        unit_id="unit_1",
        extraction_id="ext_1",
        relationship_source="persisted",
        business_sentence="在职职工住院支付比例为80%。",
        source_text="政策原文",
        fields=[],
        confidence=KnowledgeConfidence(
            completeness=1, accuracy=None, source_fidelity=1,
            model_confidence=1, value_domain_compliance=None, overall=1,
        ),
        citations=[],
    )

    class Workbench:
        def list_documents(self):
            return WorkbenchDocumentList(items=[WorkbenchDocumentSummary(
                doc_id="doc_1", doc_title="政策", approved_unit_count=1, knowledge_count=1,
            )], total=1)

        def get_document(self, doc_id: str):
            return KnowledgeWorkbenchDocument(
                doc_id=doc_id, doc_title="政策", contract_version="2",
                units=[ApprovedUnit(
                    unit_id="unit_1", doc_id=doc_id, doc_title="政策", path=["第一条"],
                    source_text="政策原文", order_no=1, status="reviewed",
                    knowledge_count=1, knowledge=[item],
                )],
            )

    class Provider:
        dim = 2

        def encode(self, texts: list[str]):
            return [[0.1, 0.2] for _ in texts]

    facts, rules = KnowledgeWorkbenchReleaseSource(Workbench(), Provider()).records()

    assert len(facts) == 1
    assert rules[0]["rule_id"] == "kn_stable"
