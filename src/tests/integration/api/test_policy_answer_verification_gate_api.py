"""答案验证发布门禁 API 集成测试。"""
from __future__ import annotations

import os

os.environ["USE_MEMORY_STORAGE"] = "1"

from fastapi.testclient import TestClient

from src.config import production as production_config
from src.knowledge_extension.rule_explanation.answer_verification.gate_models import (
    AnswerVerificationRun,
)
from src.knowledge_extension.rule_explanation.answer_verification.gate_service import (
    PolicyAnswerVerificationGateService,
)
from src.knowledge_extension.rule_explanation.answer_verification.gate_store import (
    InMemoryAnswerVerificationGateStore,
)
from src.knowledge_extension.rule_explanation.answer_verification.models import (
    AnswerCitation,
    AnswerEvidenceRef,
    KnowledgeAnswerVerificationDimension,
    QueryPlanItem,
    RuleRecord,
)
from src.knowledge_extension.rule_explanation.answer_verification.verifier import (
    source_text_hash,
)
from src.knowledge_extension.rule_explanation.quality_models import (
    AnswerVerificationFixture,
    KnowledgeRelease,
    PolicyQATestCase,
    QualityRun,
)
from src.knowledge_extension.rule_explanation.quality_store import (
    InMemoryPolicyQualityStore,
)
from src.runtime.api import policy_workbench_routes
from src.runtime.api.app import create_app

PREFIX = "/api/v1/medical-insurance-ai-agent/policy-workbench"
SOURCE_TEXT = "职工支付15%，退休人员个人支付比例为职工的60%。"
RULE = RuleRecord(
    rule_id="rule-1",
    policy_id="doc-1",
    source_text=SOURCE_TEXT,
    source_text_hash=source_text_hash(SOURCE_TEXT),
    rule_value="15%",
    payment_ratio="0.15",
    amount_band="650-30000",
)


class StubPort:
    def get_rule_by_id(self, rule_id: str) -> RuleRecord | None:
        return RULE if rule_id == "rule-1" else None

    def find_rules_by_text(self, text: str, *, limit: int = 5) -> list[RuleRecord]:
        return [RULE] if text and text in RULE.source_text else []

    def find_similar_rules(self, text: str, *, limit: int = 5) -> list[RuleRecord]:
        return []

    def find_rules_by_title(self, title: str, *, limit: int = 5) -> list[RuleRecord]:
        return []


class StubSearcher:
    def search(self, release: KnowledgeRelease, case: PolicyQATestCase) -> list[str]:
        return ["rule-1"]


class SnapshotStore:
    def __init__(self) -> None:
        self.saved = []

    def save(self, snapshot):
        self.saved.append(snapshot)
        return snapshot

    def get(self, snapshot_id: str):
        return None

    def list(self):
        return []


def make_fixture() -> AnswerVerificationFixture:
    return AnswerVerificationFixture(
        answer="统筹自付按政策分段计算。",
        citations=[AnswerCitation(title="职工医保住院待遇政策", excerpt=SOURCE_TEXT)],
        expected_evidence=[
            AnswerEvidenceRef(
                rule_id="rule-1",
                rule_value="15%",
                payment_ratio="0.15",
                amount_band="650-30000",
            )
        ],
        scenario="pooling_self_pay",
        planned_queries=[QueryPlanItem(query_name="employee_ratio", required=True)],
        calculation_trace={"steps": [{"description": "职工自付比例 15%，退休人员系数 60%，实际 9%"}]},
        gated_dimensions=[
            KnowledgeAnswerVerificationDimension.CITATION_AUTHENTICITY,
            KnowledgeAnswerVerificationDimension.CONCLUSION_CONSISTENCY,
            KnowledgeAnswerVerificationDimension.CALCULATION_CONSISTENCY,
            KnowledgeAnswerVerificationDimension.COVERAGE_COMPLETENESS,
        ],
    )


def make_quality_store() -> InMemoryPolicyQualityStore:
    store = InMemoryPolicyQualityStore()
    store.save_test_case(PolicyQATestCase(
        case_id="case-1",
        name="答案验证用例",
        query="统筹自付为什么这么多？",
        mode="semantic",
        answer_verification=make_fixture(),
    ))
    active = KnowledgeRelease(
        release_id="active-rel",
        status="active",
        facts_collection="facts_active",
        rules_collection="rules_active",
        contract_version="v1",
        case_set_version=store.current_case_set_version(),
        config_hash="hash",
    )
    candidate = KnowledgeRelease(
        release_id="rel-1",
        status="passed",
        facts_collection="facts_rel_1",
        rules_collection="rules_rel_1",
        contract_version="v1",
        case_set_version=store.current_case_set_version(),
        config_hash="hash",
    )
    store.create_release(active)
    store.active_release_id = active.release_id
    store.create_release(candidate)
    store.save_run(QualityRun(
        run_id="qrun-1",
        release_id="rel-1",
        baseline_release_id="active-rel",
        case_set_version=store.current_case_set_version(),
        config_hash="hash",
        status="passed",
        candidate_score=1.0,
        baseline_score=0.5,
        consistency_score=1.0,
    ))
    return store


def make_client(monkeypatch, *, gate_store: InMemoryAnswerVerificationGateStore | None = None):
    quality_store = make_quality_store()
    gate_store = gate_store or InMemoryAnswerVerificationGateStore()
    service = PolicyAnswerVerificationGateService(
        quality_store,
        gate_store,
        StubSearcher(),
        lambda collection_name: StubPort(),
    )
    monkeypatch.setattr(policy_workbench_routes, "_get_quality_store", lambda: quality_store)
    monkeypatch.setattr(policy_workbench_routes, "_get_snapshot_store", lambda: SnapshotStore())
    monkeypatch.setattr(
        policy_workbench_routes,
        "_validate_governed_release_source_before_promote",
        lambda release, active_retry=False: None,
    )
    app = create_app()
    app.dependency_overrides[
        policy_workbench_routes.get_answer_verification_gate_store
    ] = lambda: gate_store
    app.dependency_overrides[
        policy_workbench_routes.get_answer_verification_gate_service
    ] = lambda: service
    return TestClient(app), quality_store, gate_store


def test_post_test_get_latest_and_gate_status(monkeypatch) -> None:
    monkeypatch.setattr(
        production_config, "POLICY_RELEASE_ANSWER_VERIFICATION_GATE_ENABLED", True
    )
    client, _, _ = make_client(monkeypatch)
    response = client.post(f"{PREFIX}/releases/rel-1/answer-verification/test")
    assert response.status_code == 200
    assert response.json()["status"] == "passed"

    latest = client.get(f"{PREFIX}/releases/rel-1/answer-verification/latest")
    assert latest.status_code == 200
    assert latest.json()["run"]["status"] == "passed"
    assert latest.json()["case_results"][0]["status"] == "passed"

    gate = client.get(f"{PREFIX}/releases/rel-1/gate-status")
    body = gate.json()
    assert gate.status_code == 200
    assert body["answer_verification_gate_enabled"] is True
    assert body["latest_answer_verification_run"]["status"] == "passed"
    assert body["answer_verification_blocked_reasons"] == []


def test_promote_gate_disabled_allows_without_answer_run(monkeypatch) -> None:
    monkeypatch.setattr(
        production_config, "POLICY_RELEASE_ANSWER_VERIFICATION_GATE_ENABLED", False
    )
    client, _, _ = make_client(monkeypatch)
    response = client.post(f"{PREFIX}/releases/rel-1/promote", json={"reviewed_by": "tester"})
    assert response.status_code == 200
    assert response.json()["status"] == "active"

    gate = client.get(f"{PREFIX}/releases/rel-1/gate-status")
    assert gate.json()["answer_verification_gate_enabled"] is False
    assert gate.json()["answer_verification_blocked_reasons"] == ["skipped: 答案验证门禁未启用"]


def test_promote_gate_enabled_blocks_without_run(monkeypatch) -> None:
    monkeypatch.setattr(
        production_config, "POLICY_RELEASE_ANSWER_VERIFICATION_GATE_ENABLED", True
    )
    client, _, _ = make_client(monkeypatch)
    response = client.post(f"{PREFIX}/releases/rel-1/promote", json={"reviewed_by": "tester"})
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "POLICY_RELEASE_ANSWER_VERIFICATION_GATE_BLOCKED"


def test_promote_gate_enabled_blocks_failed_run(monkeypatch) -> None:
    monkeypatch.setattr(
        production_config, "POLICY_RELEASE_ANSWER_VERIFICATION_GATE_ENABLED", True
    )
    gate_store = InMemoryAnswerVerificationGateStore()
    gate_store.save_run(AnswerVerificationRun(
        run_id="avrun-failed",
        release_id="rel-1",
        case_set_version=1,
        status="failed",
        blocked_reasons=["case-1: 维度 conclusion_consistency 未通过: failed"],
    ))
    client, _, _ = make_client(monkeypatch, gate_store=gate_store)
    response = client.post(f"{PREFIX}/releases/rel-1/promote", json={"reviewed_by": "tester"})
    assert response.status_code == 409
    assert "blocked_reasons" in response.json()["detail"]["audit_event"]


def test_promote_gate_enabled_allows_passed_run(monkeypatch) -> None:
    monkeypatch.setattr(
        production_config, "POLICY_RELEASE_ANSWER_VERIFICATION_GATE_ENABLED", True
    )
    gate_store = InMemoryAnswerVerificationGateStore()
    gate_store.save_run(AnswerVerificationRun(
        run_id="avrun-passed",
        release_id="rel-1",
        case_set_version=1,
        status="passed",
    ))
    client, _, _ = make_client(monkeypatch, gate_store=gate_store)
    response = client.post(f"{PREFIX}/releases/rel-1/promote", json={"reviewed_by": "tester"})
    assert response.status_code == 200
    assert response.json()["status"] == "active"
