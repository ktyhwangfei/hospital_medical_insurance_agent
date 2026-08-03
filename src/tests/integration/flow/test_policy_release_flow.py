from __future__ import annotations

from src.knowledge_extension.rule_explanation.quality_models import (
    KnowledgeRelease,
    PolicyQATestCase,
    QualityRun,
)
from src.knowledge_extension.rule_explanation.quality_service import PolicyQualityService
from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore
from src.knowledge_extension.rule_explanation.release_index import ReleaseIndexBuilder


QUALITY_CONFIG_HASH = "197ceb8357b8a65b5db3db7044838ff7fd7010ab36caf2b11270e4ab61607e22"


class HealthyBackend:
    def create(self, kind: str, collection_name: str) -> None:
        pass

    def insert(self, kind: str, collection_name: str, records: list[dict]) -> None:
        pass

    def load(self, collection_name: str) -> None:
        pass

    def is_healthy(self, collection_name: str) -> bool:
        return True


class ReleaseSearcher:
    def search(self, release: KnowledgeRelease, case: PolicyQATestCase) -> list[str]:
        return ["kn_expected"] if release.release_id == "candidate" else []


def test_candidate_build_test_and_manual_atomic_promotion_flow() -> None:
    store = InMemoryPolicyQualityStore()
    store.save_test_case(PolicyQATestCase(
        case_id="case_required",
        name="经典必测用例",
        query="职工住院支付比例",
        mode="semantic",
        expected_knowledge_ids=["kn_expected"],
    ))
    store.save_release(KnowledgeRelease(
        release_id="baseline",
        status="passed",
        facts_collection="policy_facts_baseline",
        rules_collection="policy_rules_baseline",
        contract_version="1",
        case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH,
    ))
    store.save_run(QualityRun(
        run_id="run_baseline", release_id="baseline", case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH, status="passed",
    ))
    store.promote_release("baseline", "reviewer_a")
    store.save_release(KnowledgeRelease(
        release_id="candidate",
        status="building",
        facts_collection="policy_facts_candidate",
        rules_collection="policy_rules_candidate",
        contract_version="2",
        case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH,
    ))

    ready = ReleaseIndexBuilder(store, HealthyBackend()).build(
        "candidate", facts=[{"fact_id": "f1"}], rules=[{"rule_id": "r1"}]
    )
    assert ready.status == "ready"

    run = PolicyQualityService(store, ReleaseSearcher()).run_release(
        "candidate", repeat_count=3
    )
    assert run.status == "passed"
    assert store.get_active_release().release_id == "baseline"  # type: ignore[union-attr]

    promoted = store.promote_release("candidate", "reviewer_b")
    assert promoted.status == "active"
    assert store.get_active_release().release_id == "candidate"  # type: ignore[union-attr]
    assert store.get_release("baseline").status == "retired"  # type: ignore[union-attr]
