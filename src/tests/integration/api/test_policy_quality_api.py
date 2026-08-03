from __future__ import annotations

from fastapi.testclient import TestClient

from src.knowledge_extension.rule_explanation.quality_models import KnowledgeRelease
from src.knowledge_extension.rule_explanation.quality_service import PolicyQualityService
from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore
from src.runtime.api.app import create_app


PREFIX = "/api/v1/medical-insurance-ai-agent/policy-workbench"


class Searcher:
    def search(self, release, case) -> list[str]:
        return ["kn_expected"] if release.release_id == "candidate" else []


def _client(monkeypatch) -> tuple[TestClient, InMemoryPolicyQualityStore]:
    from src.runtime.api import policy_workbench_routes

    store = InMemoryPolicyQualityStore()
    service = PolicyQualityService(store, Searcher())
    monkeypatch.setattr(policy_workbench_routes, "_get_quality_store", lambda: store)
    monkeypatch.setattr(policy_workbench_routes, "_get_quality_service", lambda: service)

    class ContentSource:
        def records(self):
            return ([{"fact_id": "fact_1"}], [{"rule_id": "kn_1"}])

    class Builder:
        def build(self, release_id: str, *, facts, rules):
            release = store.get_release(release_id)
            assert release is not None and facts and rules
            return store.save_release(release.model_copy(update={"status": "ready"}))

    monkeypatch.setattr(policy_workbench_routes, "_get_release_content_source", lambda: ContentSource())
    monkeypatch.setattr(policy_workbench_routes, "_get_release_index_builder", lambda: Builder())
    return TestClient(create_app()), store


def test_test_case_create_and_list(monkeypatch) -> None:
    client, _ = _client(monkeypatch)

    created = client.post(f"{PREFIX}/test-cases", json={
        "case_id": "case_1",
        "name": "职工住院比例",
        "query": "职工住院支付比例",
        "mode": "semantic",
        "expected_knowledge_ids": ["kn_expected"],
        "required": True,
    })
    listed = client.get(f"{PREFIX}/test-cases")

    assert created.status_code == 201
    assert created.json()["case_set_version"] == 1
    assert listed.status_code == 200
    assert listed.json()[0]["case_id"] == "case_1"


def test_candidate_release_uses_one_versioned_collection_pair(monkeypatch) -> None:
    client, _ = _client(monkeypatch)

    response = client.post(f"{PREFIX}/releases", json={
        "release_id": "rel_20260803_01",
        "contract_version": "2",
        "config_hash": "cfg_1",
    })

    assert response.status_code == 201
    assert response.json()["status"] == "building"
    assert response.json()["facts_collection"] == "policy_facts_rel_20260803_01"
    assert response.json()["rules_collection"] == "policy_rules_rel_20260803_01"
    built = client.post(f"{PREFIX}/releases/rel_20260803_01/build")
    assert built.status_code == 200
    assert built.json()["status"] == "ready"
    listed = client.get(f"{PREFIX}/releases")
    assert listed.status_code == 200
    assert listed.json()[0]["release_id"] == "rel_20260803_01"


def test_run_detail_and_manual_promotion(monkeypatch) -> None:
    client, store = _client(monkeypatch)
    case_response = client.post(f"{PREFIX}/test-cases", json={
        "case_id": "case_1",
        "name": "职工住院比例",
        "query": "职工住院支付比例",
        "mode": "semantic",
        "expected_knowledge_ids": ["kn_expected"],
    })
    assert case_response.status_code == 201
    store.save_release(KnowledgeRelease(
        release_id="baseline",
        status="passed",
        facts_collection="policy_facts_baseline",
        rules_collection="policy_rules_baseline",
        contract_version="1",
        case_set_version=1,
        config_hash="cfg_1",
    ))
    store.promote_release("baseline", "reviewer_a")
    store.save_release(KnowledgeRelease(
        release_id="candidate",
        status="ready",
        facts_collection="policy_facts_candidate",
        rules_collection="policy_rules_candidate",
        contract_version="2",
        case_set_version=1,
        config_hash="cfg_1",
    ))

    run_response = client.post(
        f"{PREFIX}/releases/candidate/test", json={"repeat_count": 3}
    )
    assert run_response.status_code == 200
    run = run_response.json()
    assert run["status"] == "passed"
    detail = client.get(f"{PREFIX}/quality-runs/{run['run_id']}")
    assert detail.status_code == 200
    case_results = client.get(f"{PREFIX}/quality-runs/{run['run_id']}/case-results")
    assert case_results.status_code == 200
    assert len(case_results.json()) == 6
    assert {item["target"] for item in case_results.json()} == {"candidate", "baseline"}
    assert client.get(f"{PREFIX}/releases/active").json()["release_id"] == "baseline"

    promoted = client.post(
        f"{PREFIX}/releases/candidate/promote", json={"reviewed_by": "reviewer_b"}
    )
    assert promoted.status_code == 200
    assert promoted.json()["status"] == "active"


def test_blocked_promotion_returns_409_and_preserves_active_release(monkeypatch) -> None:
    client, store = _client(monkeypatch)
    store.save_release(KnowledgeRelease(
        release_id="baseline",
        status="passed",
        facts_collection="policy_facts_baseline",
        rules_collection="policy_rules_baseline",
        contract_version="1",
        case_set_version=0,
        config_hash="cfg_1",
    ))
    store.promote_release("baseline", "reviewer_a")
    store.save_release(KnowledgeRelease(
        release_id="failed",
        status="failed",
        facts_collection="policy_facts_failed",
        rules_collection="policy_rules_failed",
        contract_version="2",
        case_set_version=0,
        config_hash="cfg_1",
    ))

    response = client.post(
        f"{PREFIX}/releases/failed/promote", json={"reviewed_by": "reviewer_b"}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "POLICY_RELEASE_GATE_BLOCKED"
    assert store.get_active_release().release_id == "baseline"  # type: ignore[union-attr]
