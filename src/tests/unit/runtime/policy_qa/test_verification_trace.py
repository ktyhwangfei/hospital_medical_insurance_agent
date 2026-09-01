"""MVU-3 单元测试：答案验证 trace 捕获/存储与 verify_qa_turn 编排。

覆盖：
- InMemoryAnswerVerificationTraceStore 存取语义；
- build_verification_envelope 字段映射（血缘/hash/命中数/缺失规则/场景）；
- verify_qa_turn 三分支：完整 trace / 无 trace 降级 / 未知 id；
- 知识源异常 fail-closed（blocked_by_evaluator，绝不伪造通过）。
"""
from __future__ import annotations

import os

os.environ["USE_MEMORY_STORAGE"] = "1"

from types import SimpleNamespace

from src.knowledge_extension.rule_explanation.answer_verification.models import (
    KnowledgeAnswerVerificationStatus,
    RuleRecord,
)
from src.knowledge_extension.rule_explanation.answer_verification.verifier import (
    source_text_hash,
)
from src.runtime.policy_qa.verification_trace import (
    InMemoryAnswerVerificationTraceStore,
    build_verification_envelope,
    verify_qa_turn,
)

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
    """确定性规则知识源桩。"""

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


class _ExplodingPort(_StubPort):
    def get_rule_by_id(self, rule_id: str) -> RuleRecord | None:
        raise ConnectionError("milvus down")

    def find_rules_by_text(self, text: str, *, limit: int = 5) -> list[RuleRecord]:
        raise ConnectionError("milvus down")


def _make_public_result(*, excerpt: str = _SOURCE_TEXT) -> SimpleNamespace:
    return SimpleNamespace(
        answer="统筹自付按政策分段计算。",
        answer_status="complete",
        citations=[SimpleNamespace(title="职工医保住院待遇政策", excerpt=excerpt)],
    )


def _make_retrieval_result(*, source_text: str = _SOURCE_TEXT) -> SimpleNamespace:
    evidence = SimpleNamespace(
        evidence_id="rule-1",
        rule_id="rule-1",
        rule_instance_key="ik-1",
        policy_id="doc-1",
        clause_id="c-1",
        query_name="employee_inpatient_tertiary_segment_ratio",
        source_text=source_text,
        rule_value="15%",
        payment_ratio="0.15",
        amount_band="650-30000",
        psn_type="退休人员",
    )
    return SimpleNamespace(
        selected_evidence=[evidence],
        planned_queries=[{"query_name": "employee_inpatient_tertiary_segment_ratio", "required": True}],
        query_results={"employee_inpatient_tertiary_segment_ratio": [{"rule_id": "rule-1"}]},
        missing_required_rules=[],
    )


def _make_envelope(qa_turn_id: str = "qat_trace_1", **overrides):
    kwargs = {
        "qa_turn_id": qa_turn_id,
        "question": "统筹自付为什么这么多？",
        "public_result": _make_public_result(),
        "retrieval_result": _make_retrieval_result(),
        "calculation_trace": {
            "steps": [{"description": "职工自付比例 15%，退休人员系数 60%，实际 9%"}]
        },
        "scenario": "pooling_self_pay",
        "context": {"psn_type": "退休人员"},
    }
    kwargs.update(overrides)
    return build_verification_envelope(**kwargs)


class TestTraceStore:
    def test_save_and_get_roundtrip(self):
        store = InMemoryAnswerVerificationTraceStore()
        envelope = _make_envelope()
        store.save(envelope)
        assert store.get("qat_trace_1") is envelope

    def test_get_unknown_returns_none(self):
        store = InMemoryAnswerVerificationTraceStore()
        assert store.get("qat_missing") is None

    def test_save_overwrites_same_turn(self):
        store = InMemoryAnswerVerificationTraceStore()
        store.save(_make_envelope(question="第一问"))
        store.save(_make_envelope(question="第二问"))
        stored = store.get("qat_trace_1")
        assert stored is not None
        assert stored.question == "第二问"


class TestBuildVerificationEnvelope:
    def test_maps_evidence_lineage_and_hash(self):
        envelope = _make_envelope()
        assert envelope.qa_turn_id == "qat_trace_1"
        assert envelope.answer_status == "complete"
        assert len(envelope.citations) == 1
        assert envelope.citations[0].excerpt == _SOURCE_TEXT
        evidence = envelope.internal_evidence[0]
        assert evidence.rule_id == "rule-1"
        assert evidence.rule_instance_key == "ik-1"
        assert evidence.policy_id == "doc-1"
        assert evidence.source_text_hash == source_text_hash(_SOURCE_TEXT)
        assert evidence.payment_ratio == "0.15"

    def test_maps_planned_queries_with_hit_counts(self):
        envelope = _make_envelope()
        assert envelope.scenario == "pooling_self_pay"
        assert len(envelope.planned_queries) == 1
        query = envelope.planned_queries[0]
        assert query.query_name == "employee_inpatient_tertiary_segment_ratio"
        assert query.required is True
        assert query.hit_count == 1
        assert envelope.missing_required_rules == []

    def test_overview_without_retrieval_has_empty_evidence(self):
        envelope = _make_envelope(retrieval_result=None, scenario="")
        assert envelope.internal_evidence == []
        assert envelope.planned_queries == []
        assert envelope.scenario == ""

    def test_invalid_answer_status_falls_back_to_unavailable(self):
        public = _make_public_result()
        public.answer_status = "weird"
        envelope = _make_envelope(public_result=public)
        assert envelope.answer_status == "unavailable"


class TestVerifyQaTurn:
    def test_full_trace_passes_with_matching_knowledge_source(self):
        store = InMemoryAnswerVerificationTraceStore()
        store.save(_make_envelope())
        outcome = verify_qa_turn(
            "qat_trace_1", store=store, port=_StubPort({"rule-1": _RULE})
        )
        assert outcome is not None
        assert outcome.trace_available is True
        assert outcome.degraded is False
        assert outcome.verification.status == KnowledgeAnswerVerificationStatus.PASSED
        assert set(outcome.verification.dimensions) == {
            "citation_authenticity",
            "conclusion_consistency",
            "calculation_consistency",
            "coverage_completeness",
        }

    def test_unknown_turn_returns_none(self):
        store = InMemoryAnswerVerificationTraceStore()
        outcome = verify_qa_turn("qat_nonexistent", store=store, port=_StubPort())
        assert outcome is None

    def test_degraded_when_task_exists_without_trace(self):
        from src.runtime.task_closure.service import create_task

        create_task(
            task_id="qat_degraded_1",
            task_type="policy_qa",
            description="政策问答",
            responsible_role="cashier",
            workflow_id="wf-degraded",
            executor_type="skill",
            input_data={"question_excerpt": "统筹自付？", "user_id": "u1", "tenant_id": "default"},
            output_data={"answer_excerpt": "按政策计算。", "answer_status": "complete"},
            status="completed",
        )
        store = InMemoryAnswerVerificationTraceStore()
        outcome = verify_qa_turn("qat_degraded_1", store=store, port=_StubPort())
        assert outcome is not None
        assert outcome.degraded is True
        assert outcome.trace_available is False
        # 公开-only 降级：无引用/无内部证据 → 全维度 not_evaluable
        assert outcome.verification.status == KnowledgeAnswerVerificationStatus.NOT_EVALUABLE

    def test_knowledge_source_failure_is_fail_closed(self):
        store = InMemoryAnswerVerificationTraceStore()
        store.save(_make_envelope())
        outcome = verify_qa_turn("qat_trace_1", store=store, port=_ExplodingPort())
        assert outcome is not None
        assert outcome.verification.status == KnowledgeAnswerVerificationStatus.BLOCKED_BY_EVALUATOR

    def test_no_port_is_blocked_not_passed(self):
        store = InMemoryAnswerVerificationTraceStore()
        store.save(_make_envelope())
        outcome = verify_qa_turn("qat_trace_1", store=store, port=None)
        assert outcome is not None
        assert outcome.verification.status == KnowledgeAnswerVerificationStatus.BLOCKED_BY_EVALUATOR

    def test_tampered_citation_fails_closed(self):
        store = InMemoryAnswerVerificationTraceStore()
        store.save(_make_envelope(public_result=_make_public_result(excerpt="凭空捏造的政策原文。")))
        outcome = verify_qa_turn(
            "qat_trace_1", store=store, port=_StubPort({"rule-1": _RULE})
        )
        assert outcome is not None
        assert outcome.verification.status == KnowledgeAnswerVerificationStatus.FAILED
        citation_dim = outcome.verification.dimensions["citation_authenticity"]
        assert citation_dim.status == KnowledgeAnswerVerificationStatus.FAILED
        codes = {failure.code for failure in citation_dim.failures}
        assert codes & {"CITATION_EXCERPT_NOT_FOUND", "CITATION_UNVERIFIED"}
