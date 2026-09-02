"""答案验证发布门禁单元测试。"""
from __future__ import annotations

import pytest

from src.knowledge_extension.rule_explanation.answer_verification.gate_models import (
    AnswerVerificationRun,
)
from src.knowledge_extension.rule_explanation.answer_verification.gate_service import (
    UNSUPPORTED_CITATION_SUPPORT_REASON,
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
)
from src.knowledge_extension.rule_explanation.quality_store import (
    InMemoryPolicyQualityStore,
)


SOURCE_TEXT = "职工支付15%，退休人员个人支付比例为职工的60%。"
RULE = RuleRecord(
    rule_id="rule-1",
    policy_id="doc-1",
    source_text=SOURCE_TEXT,
    source_text_hash=source_text_hash(SOURCE_TEXT),
    rule_value="15%",
    payment_ratio="0.15",
    amount_band="650-30000",
    psn_type="退休人员",
    query_name="employee_ratio",
)


class StubPort:
    def __init__(self, rules: dict[str, RuleRecord] | None = None, *, fail: bool = False) -> None:
        self._rules = rules or {}
        self._fail = fail

    def get_rule_by_id(self, rule_id: str) -> RuleRecord | None:
        if self._fail:
            raise RuntimeError("boom")
        return self._rules.get(rule_id)

    def find_rules_by_text(self, text: str, *, limit: int = 5) -> list[RuleRecord]:
        return [rule for rule in self._rules.values() if text and text in rule.source_text][:limit]

    def find_similar_rules(self, text: str, *, limit: int = 5) -> list[RuleRecord]:
        return []

    def find_rules_by_title(self, title: str, *, limit: int = 5) -> list[RuleRecord]:
        return []


class StubSearcher:
    def __init__(self, ids: list[str] | None = None, *, fail: bool = False) -> None:
        self._ids = ids if ids is not None else ["rule-1"]
        self._fail = fail

    def search(self, release: KnowledgeRelease, case: PolicyQATestCase) -> list[str]:
        if self._fail:
            raise RuntimeError("search failed")
        return list(self._ids)


def make_fixture(
    *,
    gated_dimensions: list[KnowledgeAnswerVerificationDimension] | None = None,
    payment_ratio: str = "0.15",
    scenario: str = "pooling_self_pay",
    calculation_trace: dict | None = None,
) -> AnswerVerificationFixture:
    return AnswerVerificationFixture(
        answer="统筹自付按政策分段计算。",
        citations=[AnswerCitation(title="职工医保住院待遇政策", excerpt=SOURCE_TEXT)],
        expected_evidence=[
            AnswerEvidenceRef(
                rule_id="rule-1",
                rule_value="15%",
                payment_ratio=payment_ratio,
                amount_band="650-30000",
                psn_type="退休人员",
            )
        ],
        scenario=scenario,
        planned_queries=[QueryPlanItem(query_name="employee_ratio", required=True)],
        calculation_trace=calculation_trace
        if calculation_trace is not None
        else {"steps": [{"description": "职工自付比例 15%，退休人员系数 60%，实际 9%"}]},
        gated_dimensions=gated_dimensions
        if gated_dimensions is not None
        else [
            KnowledgeAnswerVerificationDimension.CITATION_AUTHENTICITY,
            KnowledgeAnswerVerificationDimension.CONCLUSION_CONSISTENCY,
            KnowledgeAnswerVerificationDimension.CALCULATION_CONSISTENCY,
            KnowledgeAnswerVerificationDimension.COVERAGE_COMPLETENESS,
        ],
    )


def make_case(
    case_id: str = "case-1",
    *,
    required: bool = True,
    fixture: AnswerVerificationFixture | None = None,
) -> PolicyQATestCase:
    return PolicyQATestCase(
        case_id=case_id,
        name="答案验证用例",
        query="统筹自付为什么这么多？",
        mode="semantic",
        required=required,
        answer_verification=fixture,
    )


def make_service(
    cases: list[PolicyQATestCase],
    *,
    searcher: StubSearcher | None = None,
    port: StubPort | None = None,
) -> tuple[PolicyAnswerVerificationGateService, InMemoryAnswerVerificationGateStore]:
    quality_store = InMemoryPolicyQualityStore()
    for case in cases:
        quality_store.save_test_case(case)
    release = KnowledgeRelease(
        release_id="rel-1",
        status="passed",
        facts_collection="facts_rel_1",
        rules_collection="rules_rel_1",
        contract_version="v1",
        case_set_version=quality_store.current_case_set_version(),
        config_hash="hash",
    )
    quality_store.create_release(release)
    gate_store = InMemoryAnswerVerificationGateStore()
    service = PolicyAnswerVerificationGateService(
        quality_store,
        gate_store,
        searcher or StubSearcher(),
        lambda collection_name: port if port is not None else StubPort({"rule-1": RULE}),
    )
    return service, gate_store


def test_missing_fixture_blocks_required_case() -> None:
    service, store = make_service([make_case(fixture=None)])
    run = service.run_release("rel-1")
    assert run.status == "failed"
    assert "缺少答案验证夹具" in run.blocked_reasons[0]
    assert store.list_case_results(run.run_id)[0].status == "failed"


def test_four_implemented_dimensions_all_pass() -> None:
    service, store = make_service([make_case(fixture=make_fixture())])
    run = service.run_release("rel-1")
    result = store.list_case_results(run.run_id)[0]
    assert run.status == "passed"
    assert result.status == "passed"
    assert set(result.verification.dimensions) == {
        "citation_authenticity",
        "conclusion_consistency",
        "calculation_consistency",
        "coverage_completeness",
    }


def test_single_gated_dimension_failure_blocks() -> None:
    service, store = make_service([
        make_case(fixture=make_fixture(payment_ratio="0.20"))
    ])
    run = service.run_release("rel-1")
    result = store.list_case_results(run.run_id)[0]
    assert run.status == "failed"
    assert "conclusion_consistency" in result.blocked_reasons[0]


def test_not_evaluable_undeclared_dimension_is_skipped_not_blocking() -> None:
    fixture = make_fixture(
        gated_dimensions=[KnowledgeAnswerVerificationDimension.CITATION_AUTHENTICITY],
        scenario="",
        calculation_trace=None,
    )
    service, store = make_service([make_case(fixture=fixture)])
    run = service.run_release("rel-1")
    result = store.list_case_results(run.run_id)[0]
    assert run.status == "passed"
    assert KnowledgeAnswerVerificationDimension.COVERAGE_COMPLETENESS in result.skipped_dimensions
    assert result.verification.dimensions["coverage_completeness"].status == "not_evaluable"


def test_declared_citation_support_dimension_blocks() -> None:
    fixture = make_fixture(
        gated_dimensions=[KnowledgeAnswerVerificationDimension.CITATION_SUPPORT]
    )
    service, store = make_service([make_case(fixture=fixture)])
    run = service.run_release("rel-1")
    result = store.list_case_results(run.run_id)[0]
    assert run.status == "failed"
    assert UNSUPPORTED_CITATION_SUPPORT_REASON in result.blocked_reasons


def test_knowledge_source_exception_fail_closed() -> None:
    service, store = make_service([make_case(fixture=make_fixture())], port=StubPort(fail=True))
    run = service.run_release("rel-1")
    result = store.list_case_results(run.run_id)[0]
    assert run.status == "failed"
    assert any("规则知识源解析异常" in reason for reason in result.blocked_reasons)


def test_internal_evidence_source_text_hash_is_filled_from_port() -> None:
    service, store = make_service([make_case(fixture=make_fixture())])
    run = service.run_release("rel-1")
    citation = store.list_case_results(run.run_id)[0].verification.dimensions[
        "citation_authenticity"
    ].details["citations"][0]
    assert citation["link_method"] == "internal_id_match"
    assert citation["matched_rule_id"] == "rule-1"


def test_non_required_case_without_fixture_does_not_block() -> None:
    service, _ = make_service([
        make_case("required", fixture=make_fixture()),
        make_case("optional", required=False, fixture=None),
    ])
    run = service.run_release("rel-1")
    assert run.status == "passed"


def test_in_memory_gate_store_latest_and_case_results() -> None:
    store = InMemoryAnswerVerificationGateStore()
    first = AnswerVerificationRun(
        run_id="run-1",
        release_id="rel-1",
        case_set_version=1,
        status="failed",
    )
    second = first.model_copy(update={"run_id": "run-2", "status": "passed"})
    store.save_run(first)
    store.save_run(second)
    assert store.get_run("run-1") == first
    assert store.get_latest_run("rel-1") == second


def test_search_exception_fail_closed() -> None:
    service, store = make_service(
        [make_case(fixture=make_fixture())],
        searcher=StubSearcher(fail=True),
    )
    run = service.run_release("rel-1")
    result = store.list_case_results(run.run_id)[0]
    assert run.status == "failed"
    assert any("检索实跑异常" in reason for reason in result.blocked_reasons)
