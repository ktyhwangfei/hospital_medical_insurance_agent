"""知识答案验证：结论一致性 / 计算一致性 / 覆盖完整性维度单元测试。

覆盖：结论一致性（证据值 vs 知识源规则值，fail-closed）、计算一致性
（退休折算 实际=职工×系数 重算 + 比例原文支撑）、覆盖完整性
（必需查询命中 + 缺失规则；无场景 → not_evaluable）与整体聚合。
"""
from __future__ import annotations

from src.knowledge_extension.rule_explanation.answer_verification.models import (
    KnowledgeAnswerVerificationDimension,
    KnowledgeAnswerVerificationInput,
    KnowledgeAnswerVerificationResult,
    KnowledgeAnswerVerificationStatus,
    QueryPlanItem,
)
from src.knowledge_extension.rule_explanation.answer_verification.verifier import (
    CALCULATION_RATIO_MISMATCH,
    CALCULATION_SEGMENT_UNSUPPORTED,
    CONCLUSION_MISSING_SOURCE,
    CONCLUSION_RULE_MISSING,
    CONCLUSION_RULE_UNLOCATED,
    CONCLUSION_VALUE_MISMATCH,
    COVERAGE_MISSING_REQUIRED_QUERY,
    COVERAGE_MISSING_REQUIRED_RULE,
    KnowledgeAnswerVerifier,
)
from src.tests.unit.knowledge_extension.answer_verification.test_citation_authenticity import (
    FakeRuleKnowledgePort,
    SRC_TEXT,
    _citation,
    _evidence,
    _rule,
)

DIMENSION = KnowledgeAnswerVerificationDimension

RETIREE_TRACE = {
    "method": "分段比例 × 退休人员优惠系数",
    "steps": [
        {"step_name": "确认起付线", "description": "起付线为 1000 元。起付线以下不计入统筹段。"},
        {"step_name": "分段计算 - 第1段", "description": "起付标准至3万元：职工自付比例 15%，退休人员系数 60%，实际 9%。"},
    ],
}


def _run(envelope: KnowledgeAnswerVerificationInput, port: FakeRuleKnowledgePort | None) -> KnowledgeAnswerVerificationResult:
    return KnowledgeAnswerVerifier(port=port).verify(envelope)


def _dimension(result: KnowledgeAnswerVerificationResult, name: str):
    return result.dimensions[name]


def _codes(dimension) -> list[str]:
    return [failure.code for failure in dimension.failures]


# ══════════════════ 结论一致性 ══════════════════

def test_conclusion_passes_when_evidence_values_match_source() -> None:
    port = FakeRuleKnowledgePort(rules=[_rule()])
    result = _run(KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_c01", answer="统筹基金支付85%", answer_status="complete",
        internal_evidence=[_evidence()],
    ), port)

    dimension = _dimension(result, "conclusion_consistency")
    assert dimension.status == KnowledgeAnswerVerificationStatus.PASSED
    assert dimension.details["verified_evidence_count"] == 1


def test_conclusion_fails_on_stale_ratio() -> None:
    # 回答使用的比例已过期：知识源当前为 80%，证据仍携带 85%
    port = FakeRuleKnowledgePort(rules=[_rule(payment_ratio="0.8")])
    result = _run(KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_c02", answer="统筹基金支付85%", answer_status="complete",
        internal_evidence=[_evidence(payment_ratio="0.85")],
    ), port)

    dimension = _dimension(result, "conclusion_consistency")
    assert dimension.status == KnowledgeAnswerVerificationStatus.FAILED
    assert CONCLUSION_VALUE_MISMATCH in _codes(dimension)
    assert result.status == KnowledgeAnswerVerificationStatus.FAILED


def test_conclusion_fails_when_rule_removed_from_source() -> None:
    port = FakeRuleKnowledgePort(rules=[_rule(rule_id="rule_999")])
    result = _run(KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_c03", answer="统筹基金支付85%", answer_status="complete",
        internal_evidence=[_evidence(rule_id="rule_gone")],
    ), port)

    dimension = _dimension(result, "conclusion_consistency")
    assert dimension.status == KnowledgeAnswerVerificationStatus.FAILED
    assert CONCLUSION_RULE_MISSING in _codes(dimension)


def test_conclusion_fails_when_rule_unlocatable() -> None:
    # 证据无 rule_id 且原文在知识源中找不到 → fail-closed
    port = FakeRuleKnowledgePort(rules=[_rule()])
    result = _run(KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_c04", answer="统筹基金支付85%", answer_status="complete",
        internal_evidence=[_evidence(rule_id="", rule_instance_key="", source_text="完全无关的另一段政策原文")],
    ), port)

    dimension = _dimension(result, "conclusion_consistency")
    assert dimension.status == KnowledgeAnswerVerificationStatus.FAILED
    assert CONCLUSION_RULE_UNLOCATED in _codes(dimension)


def test_conclusion_not_evaluable_without_evidence() -> None:
    port = FakeRuleKnowledgePort(rules=[_rule()])
    result = _run(KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_c05", answer="无法给出确定结论", answer_status="unavailable",
        internal_evidence=[],
    ), port)

    dimension = _dimension(result, "conclusion_consistency")
    assert dimension.status == KnowledgeAnswerVerificationStatus.NOT_EVALUABLE


def test_conclusion_blocked_without_source() -> None:
    result = _run(KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_c06", answer="统筹基金支付85%", answer_status="complete",
        internal_evidence=[_evidence()],
    ), None)

    dimension = _dimension(result, "conclusion_consistency")
    assert dimension.status == KnowledgeAnswerVerificationStatus.BLOCKED_BY_EVALUATOR
    assert CONCLUSION_MISSING_SOURCE in _codes(dimension)


# ══════════════════ 计算一致性（退休折算重算） ══════════════════

def test_calculation_passes_when_retiree_ratios_rederive() -> None:
    port = FakeRuleKnowledgePort(rules=[_rule()])
    result = _run(KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_c07", answer="统筹自付金额说明", answer_status="complete",
        internal_evidence=[_evidence()],
        calculation_trace=RETIREE_TRACE,
    ), port)

    dimension = _dimension(result, "calculation_consistency")
    assert dimension.status == KnowledgeAnswerVerificationStatus.PASSED
    assert dimension.details["verified_ratio_steps"] == 1


def test_calculation_fails_on_ratio_mismatch() -> None:
    # 15% × 60% = 9%，轨迹声称 12% → 重算不一致
    port = FakeRuleKnowledgePort(rules=[_rule()])
    trace = {
        "steps": [{"step_name": "分段计算 - 第1段",
                   "description": "起付标准至3万元：职工自付比例 15%，退休人员系数 60%，实际 12%。"}]
    }
    result = _run(KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_c08", answer="统筹自付金额说明", answer_status="complete",
        internal_evidence=[_evidence()],
        calculation_trace=trace,
    ), port)

    dimension = _dimension(result, "calculation_consistency")
    assert dimension.status == KnowledgeAnswerVerificationStatus.FAILED
    assert CALCULATION_RATIO_MISMATCH in _codes(dimension)
    assert result.status == KnowledgeAnswerVerificationStatus.FAILED


def test_calculation_fails_on_unsupported_segment() -> None:
    # 轨迹使用职工自付比例 20%，但证据原文只有 15% → 无支撑
    port = FakeRuleKnowledgePort(rules=[_rule()])
    trace = {
        "steps": [{"step_name": "分段计算 - 第1段",
                   "description": "起付标准至3万元：职工自付比例 20%，退休人员系数 60%，实际 12%。"}]
    }
    result = _run(KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_c09", answer="统筹自付金额说明", answer_status="complete",
        internal_evidence=[_evidence()],
        calculation_trace=trace,
    ), port)

    dimension = _dimension(result, "calculation_consistency")
    assert dimension.status == KnowledgeAnswerVerificationStatus.FAILED
    assert CALCULATION_SEGMENT_UNSUPPORTED in _codes(dimension)


def test_calculation_not_evaluable_without_trace() -> None:
    port = FakeRuleKnowledgePort(rules=[_rule()])
    result = _run(KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_c10", answer="统筹自付金额说明", answer_status="complete",
        internal_evidence=[_evidence()],
        calculation_trace=None,
    ), port)

    dimension = _dimension(result, "calculation_consistency")
    assert dimension.status == KnowledgeAnswerVerificationStatus.NOT_EVALUABLE


def test_calculation_not_evaluable_without_retiree_steps() -> None:
    port = FakeRuleKnowledgePort(rules=[_rule()])
    trace = {"steps": [{"step_name": "确认起付线", "description": "起付线为 1000 元。"}]}
    result = _run(KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_c11", answer="统筹自付金额说明", answer_status="complete",
        internal_evidence=[_evidence()],
        calculation_trace=trace,
    ), port)

    dimension = _dimension(result, "calculation_consistency")
    assert dimension.status == KnowledgeAnswerVerificationStatus.NOT_EVALUABLE


# ══════════════════ 覆盖完整性 ══════════════════

FULL_COVERAGE_QUERIES = [
    QueryPlanItem(query_name="employee_inpatient_tertiary_segment_ratio", required=True, hit_count=3),
    QueryPlanItem(query_name="retiree_personal_ratio", required=True, hit_count=1),
]


def test_coverage_passes_when_all_required_queries_hit() -> None:
    port = FakeRuleKnowledgePort(rules=[_rule()])
    result = _run(KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_c12", answer="统筹自付金额说明", answer_status="complete",
        scenario="pooling_self_pay",
        planned_queries=FULL_COVERAGE_QUERIES,
        missing_required_rules=[],
    ), port)

    dimension = _dimension(result, "coverage_completeness")
    assert dimension.status == KnowledgeAnswerVerificationStatus.PASSED
    assert dimension.details["query_count"] == 2


def test_coverage_fails_on_missing_required_query() -> None:
    port = FakeRuleKnowledgePort(rules=[_rule()])
    queries = [
        QueryPlanItem(query_name="employee_inpatient_tertiary_segment_ratio", required=True, hit_count=3),
        QueryPlanItem(query_name="retiree_personal_ratio", required=True, hit_count=0),
    ]
    result = _run(KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_c13", answer="统筹自付金额说明", answer_status="partial",
        scenario="pooling_self_pay",
        planned_queries=queries,
        missing_required_rules=[],
    ), port)

    dimension = _dimension(result, "coverage_completeness")
    assert dimension.status == KnowledgeAnswerVerificationStatus.FAILED
    assert COVERAGE_MISSING_REQUIRED_QUERY in _codes(dimension)
    assert result.status == KnowledgeAnswerVerificationStatus.FAILED


def test_coverage_fails_on_missing_required_rule() -> None:
    port = FakeRuleKnowledgePort(rules=[_rule()])
    result = _run(KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_c14", answer="统筹自付金额说明", answer_status="partial",
        scenario="pooling_self_pay",
        planned_queries=FULL_COVERAGE_QUERIES,
        missing_required_rules=["rule_retiree_formula"],
    ), port)

    dimension = _dimension(result, "coverage_completeness")
    assert dimension.status == KnowledgeAnswerVerificationStatus.FAILED
    assert COVERAGE_MISSING_REQUIRED_RULE in _codes(dimension)


def test_coverage_not_evaluable_without_scenario() -> None:
    port = FakeRuleKnowledgePort(rules=[_rule()])
    result = _run(KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_c15", answer="统筹自付金额说明", answer_status="complete",
        scenario="",
        planned_queries=[],
    ), port)

    dimension = _dimension(result, "coverage_completeness")
    assert dimension.status == KnowledgeAnswerVerificationStatus.NOT_EVALUABLE


# ══════════════════ 整体聚合 ══════════════════

def _fully_configured_envelope(port: FakeRuleKnowledgePort) -> KnowledgeAnswerVerificationInput:
    return KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_all",
        answer="统筹基金支付85%，统筹自付 2500 元",
        answer_status="complete",
        citations=[_citation(excerpt=SRC_TEXT)],
        internal_evidence=[_evidence()],
        scenario="pooling_self_pay",
        planned_queries=FULL_COVERAGE_QUERIES,
        missing_required_rules=[],
        calculation_trace=RETIREE_TRACE,
    )


def test_overall_passed_for_fully_configured_envelope() -> None:
    port = FakeRuleKnowledgePort(rules=[_rule()])
    result = _run(_fully_configured_envelope(port), port)

    assert result.status == KnowledgeAnswerVerificationStatus.PASSED
    assert all(
        _dimension(result, name).status == KnowledgeAnswerVerificationStatus.PASSED
        for name in (
            "citation_authenticity", "conclusion_consistency",
            "calculation_consistency", "coverage_completeness",
        )
    )


def test_overall_failed_when_conclusion_dimension_fails() -> None:
    # 知识源比例已更新为 80%，其余维度正常 → 整体 failed（fail-closed）
    port = FakeRuleKnowledgePort(rules=[_rule(payment_ratio="0.8")])
    result = _run(_fully_configured_envelope(port), port)

    assert result.status == KnowledgeAnswerVerificationStatus.FAILED
    assert CONCLUSION_VALUE_MISMATCH in _codes(_dimension(result, "conclusion_consistency"))
    assert _dimension(result, "citation_authenticity").status == KnowledgeAnswerVerificationStatus.PASSED
