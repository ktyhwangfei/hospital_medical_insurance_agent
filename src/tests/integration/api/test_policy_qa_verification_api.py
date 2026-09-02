"""MVU-3 API 测试：POST /policy-qa/answers/{qa_turn_id}/verification。

覆盖迭代记录 Issue 20 MVU-3 成功标准：
- 有 envelope（完整 trace）→ 返回 KnowledgeAnswerVerificationResult；
- 无 envelope 但轮次存在 → 公开-only degraded 模式；
- 伪造/过期 qa_turn_id → 404（不泄露内部细节）；
- 知识源缺失 → blocked_by_evaluator，绝不伪造通过；
- 未认证 → 401。
"""
from __future__ import annotations

import os

os.environ["USE_MEMORY_STORAGE"] = "1"

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.knowledge_extension.rule_explanation.answer_verification.models import (
    RuleRecord,
)
from src.knowledge_extension.rule_explanation.answer_verification.verifier import (
    source_text_hash,
)
from src.runtime.api import policy_qa_routes
from src.runtime.api.app import create_app
from src.runtime.policy_qa.verification_trace import (
    InMemoryAnswerVerificationTraceStore,
    build_verification_envelope,
)
from src.runtime.skill_management.regression_mining_service import RegressionPrincipal

PREFIX = "/api/v1/medical-insurance-ai-agent/policy-qa"

_SOURCE_TEXT = "职工支付15%，退休人员个人支付比例为职工的60%。"
_RULE = RuleRecord(
    rule_id="rule-1",
    policy_id="doc-1",
    source_text=_SOURCE_TEXT,
    source_text_hash=source_text_hash(_SOURCE_TEXT),
    rule_value="15%",
    payment_ratio="0.15",
    amount_band="650-30000",
    psn_type="退休人员",
)


class _StubPort:
    def __init__(self, rules: dict[str, RuleRecord] | None = None) -> None:
        self._rules = rules or {}

    def get_rule_by_id(self, rule_id: str) -> RuleRecord | None:
        return self._rules.get(rule_id)

    def find_rules_by_text(self, text: str, *, limit: int = 5) -> list[RuleRecord]:
        return [rule for rule in self._rules.values() if text and text in rule.source_text][:limit]

    def find_similar_rules(self, text: str, *, limit: int = 5) -> list[RuleRecord]:
        return []

    def find_rules_by_title(self, title: str, *, limit: int = 5) -> list[RuleRecord]:
        return []


def _make_envelope(qa_turn_id: str = "qat_verify_1", *, excerpt: str = _SOURCE_TEXT):
    evidence = SimpleNamespace(
        evidence_id="rule-1",
        rule_id="rule-1",
        rule_instance_key="ik-1",
        policy_id="doc-1",
        clause_id="c-1",
        query_name="employee_inpatient_tertiary_segment_ratio",
        source_text=_SOURCE_TEXT,
        rule_value="15%",
        payment_ratio="0.15",
        amount_band="650-30000",
        psn_type="退休人员",
    )
    retrieval = SimpleNamespace(
        selected_evidence=[evidence],
        planned_queries=[{"query_name": "employee_inpatient_tertiary_segment_ratio", "required": True}],
        query_results={"employee_inpatient_tertiary_segment_ratio": [{"rule_id": "rule-1"}]},
        missing_required_rules=[],
    )
    public = SimpleNamespace(
        answer="统筹自付按政策分段计算。",
        answer_status="complete",
        citations=[SimpleNamespace(title="职工医保住院待遇政策", excerpt=excerpt)],
    )
    return build_verification_envelope(
        qa_turn_id=qa_turn_id,
        question="统筹自付为什么这么多？",
        public_result=public,
        retrieval_result=retrieval,
        calculation_trace={"steps": [{"description": "职工自付比例 15%，退休人员系数 60%，实际 9%"}]},
        scenario="pooling_self_pay",
        context={"psn_type": "退休人员"},
    )


def _client(
    *,
    store: InMemoryAnswerVerificationTraceStore | None = None,
    port=_StubPort({"rule-1": _RULE}),
    authenticated: bool = True,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[policy_qa_routes.get_answer_verification_trace_store] = (
        lambda: store if store is not None else InMemoryAnswerVerificationTraceStore()
    )
    app.dependency_overrides[policy_qa_routes.get_answer_verification_rule_port] = lambda: port
    if authenticated:
        app.dependency_overrides[policy_qa_routes.get_policy_qa_feedback_principal] = (
            lambda: RegressionPrincipal(user_id="qa-governance", tenant_id="default")
        )
    return TestClient(app)


class TestAnswerVerificationEndpoint:
    def test_full_trace_returns_verification_result(self):
        store = InMemoryAnswerVerificationTraceStore()
        store.save(_make_envelope())
        response = _client(store=store).post(f"{PREFIX}/answers/qat_verify_1/verification")
        assert response.status_code == 200
        body = response.json()
        assert body["trace_available"] is True
        assert body["degraded"] is False
        verification = body["verification"]
        assert verification["qa_turn_id"] == "qat_verify_1"
        assert verification["status"] == "passed"
        assert set(verification["dimensions"]) == {
            "citation_authenticity",
            "conclusion_consistency",
            "calculation_consistency",
            "coverage_completeness",
        }
        citation_dim = verification["dimensions"]["citation_authenticity"]
        assert citation_dim["status"] == "passed"
        linked = citation_dim["details"]["citations"][0]
        assert linked["link_method"] == "internal_id_match"
        assert linked["matched_rule_id"] == "rule-1"

    def test_unknown_turn_returns_404(self):
        response = _client().post(f"{PREFIX}/answers/qat_nonexistent/verification")
        assert response.status_code == 404

    def test_forged_turn_id_returns_404(self):
        response = _client().post(f"{PREFIX}/answers/forged-id/verification")
        assert response.status_code == 404

    def test_degraded_when_task_exists_without_trace(self):
        from src.runtime.task_closure.service import create_task

        create_task(
            task_id="qat_degraded_api",
            task_type="policy_qa",
            description="政策问答",
            responsible_role="cashier",
            workflow_id="wf-degraded-api",
            executor_type="skill",
            input_data={"question_excerpt": "统筹自付？", "user_id": "u1", "tenant_id": "default"},
            output_data={"answer_excerpt": "按政策计算。", "answer_status": "complete"},
            status="completed",
        )
        response = _client().post(f"{PREFIX}/answers/qat_degraded_api/verification")
        assert response.status_code == 200
        body = response.json()
        assert body["degraded"] is True
        assert body["trace_available"] is False
        assert body["verification"]["status"] == "not_evaluable"

    def test_missing_knowledge_source_is_blocked_not_passed(self):
        store = InMemoryAnswerVerificationTraceStore()
        store.save(_make_envelope())
        response = _client(store=store, port=None).post(
            f"{PREFIX}/answers/qat_verify_1/verification"
        )
        assert response.status_code == 200
        verification = response.json()["verification"]
        assert verification["status"] == "blocked_by_evaluator"
        assert verification["dimensions"]["citation_authenticity"]["status"] == "blocked_by_evaluator"

    def test_tampered_citation_fails_with_stable_code(self):
        store = InMemoryAnswerVerificationTraceStore()
        store.save(_make_envelope(excerpt="凭空捏造的政策原文。"))
        response = _client(store=store).post(f"{PREFIX}/answers/qat_verify_1/verification")
        assert response.status_code == 200
        verification = response.json()["verification"]
        assert verification["status"] == "failed"
        citation_dim = verification["dimensions"]["citation_authenticity"]
        codes = {failure["code"] for failure in citation_dim["failures"]}
        assert codes & {"CITATION_EXCERPT_NOT_FOUND", "CITATION_UNVERIFIED"}

    def test_unauthenticated_read_only_verification_succeeds(self):
        """验证是只读诊断，不要求登录凭证（调用方已持有 qa_turn_id 句柄）。"""
        store = InMemoryAnswerVerificationTraceStore()
        store.save(_make_envelope())
        response = _client(store=store, authenticated=False).post(
            f"{PREFIX}/answers/qat_verify_1/verification"
        )
        assert response.status_code == 200
        assert response.json()["verification"]["status"] == "passed"
