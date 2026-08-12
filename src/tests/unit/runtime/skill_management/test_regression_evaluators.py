"""Skill 分型回归评测器单元测试。

覆盖五类可执行维度的确定性断言、缺失 evaluator 的 blocked 降级、
安全类高风险确认拦截。
"""

from __future__ import annotations

import pytest

from src.domain.skill.regression_models import (
    AnswerQualityAssertions,
    CalculationAssertions,
    CitationAssertions,
    PolicyContentAssertions,
    SafetyAssertions,
    SkillErrorDimension,
    SkillRegressionCase,
)
from src.runtime.skill_management.regression_evaluators import (
    SkillRegressionEvalFailure,
    SkillRegressionEvaluatorRegistry,
)


def _case(
    *,
    case_type: SkillErrorDimension,
    assertions,
    case_id="case-1",
) -> SkillRegressionCase:
    return SkillRegressionCase(
        case_id=case_id,
        target_skill_id="deductible",
        case_type=case_type,
        input_template={},
        expected_assertions=assertions,
        source_ref="qat_1",
        source_hash="a" * 64,
        confirmed_by="quality-user",
    )


def _codes(result) -> set[str]:
    return {f.code for f in result.failures}


# ── calculation ────────────────────────────────────────────────────


def test_calculation_evaluator_passes_within_tolerance() -> None:
    case = _case(
        case_type=SkillErrorDimension.CALCULATION,
        assertions=CalculationAssertions(
            expected_value=100.0, tolerance=0.01, must_include_steps=["统筹段"]
        ),
    )
    registry = SkillRegressionEvaluatorRegistry()
    result = registry.evaluate(
        case, output={"amount": 100.005, "steps": ["统筹段自付"]}
    )
    assert result.passed is True
    assert result.failures == []


def test_calculation_evaluator_checks_value_tolerance() -> None:
    case = _case(
        case_type=SkillErrorDimension.CALCULATION,
        assertions=CalculationAssertions(expected_value=100.0, tolerance=0.01),
    )
    registry = SkillRegressionEvaluatorRegistry()
    result = registry.evaluate(case, output={"amount": 100.02})
    assert result.passed is False
    assert "CALCULATION_TOLERANCE_EXCEEDED" in _codes(result)


def test_calculation_evaluator_checks_rounding() -> None:
    case = _case(
        case_type=SkillErrorDimension.CALCULATION,
        assertions=CalculationAssertions(
            expected_value=100.0, tolerance=0.5, rounding=2
        ),
    )
    registry = SkillRegressionEvaluatorRegistry()
    # 金额在容差内，但进位结果与 round(100.0, 2)=100.0 不一致
    result = registry.evaluate(case, output={"amount": 99.9, "rounded": 99.9})
    assert "CALCULATION_ROUNDING_MISMATCH" in _codes(result)


def test_calculation_evaluator_missing_step() -> None:
    case = _case(
        case_type=SkillErrorDimension.CALCULATION,
        assertions=CalculationAssertions(
            expected_value=100.0, tolerance=0.5, must_include_steps=["起付线"]
        ),
    )
    registry = SkillRegressionEvaluatorRegistry()
    result = registry.evaluate(case, output={"amount": 100.0, "steps": ["统筹段"]})
    assert "CALCULATION_MISSING_STEP" in _codes(result)


# ── policy_content ─────────────────────────────────────────────────


def test_policy_content_must_include_and_forbidden() -> None:
    case = _case(
        case_type=SkillErrorDimension.POLICY_CONTENT,
        assertions=PolicyContentAssertions(
            applicability="applies",
            must_include=["起付线"],
            forbidden=["不可报销"],
        ),
    )
    registry = SkillRegressionEvaluatorRegistry()
    ok = registry.evaluate(case, output={"answer": "起付线按年度累计"})
    assert ok.passed is True

    bad = registry.evaluate(case, output={"answer": "不可报销"})
    codes = _codes(bad)
    assert "POLICY_MISSING_REQUIRED_CONTENT" in codes
    assert "POLICY_FORBIDDEN_CONTENT_PRESENT" in codes


def test_policy_content_applicability_mismatch() -> None:
    case = _case(
        case_type=SkillErrorDimension.POLICY_CONTENT,
        assertions=PolicyContentAssertions(
            applicability="does_not_apply", must_include=["x"]
        ),
    )
    registry = SkillRegressionEvaluatorRegistry()
    result = registry.evaluate(case, output={"answer": "x", "applies": True})
    assert "POLICY_APPLICABILITY_MISMATCH" in _codes(result)


# ── citation ───────────────────────────────────────────────────────


def test_citation_requires_source_ids() -> None:
    case = _case(
        case_type=SkillErrorDimension.CITATION,
        assertions=CitationAssertions(required_source_ids=["doc-1", "doc-2"]),
    )
    registry = SkillRegressionEvaluatorRegistry()
    result = registry.evaluate(case, output={"sources": ["doc-1"]})
    assert result.passed is False
    assert "CITATION_MISSING_REQUIRED_SOURCE" in _codes(result)


def test_citation_support_required_missing() -> None:
    case = _case(
        case_type=SkillErrorDimension.CITATION,
        assertions=CitationAssertions(
            required_source_ids=["doc-1"], support_required="required"
        ),
    )
    registry = SkillRegressionEvaluatorRegistry()
    result = registry.evaluate(case, output={"sources": ["doc-1"], "supports_answer": False})
    assert "CITATION_SUPPORT_MISSING" in _codes(result)


# ── answer_quality ─────────────────────────────────────────────────


def test_answer_quality_must_not_include() -> None:
    case = _case(
        case_type=SkillErrorDimension.ANSWER_QUALITY,
        assertions=AnswerQualityAssertions(
            answerable=True, must_include=["起付线"], must_not_include=["脏话"]
        ),
    )
    registry = SkillRegressionEvaluatorRegistry()
    bad = registry.evaluate(case, output={"answer": "起付线 脏话"})
    assert "QUALITY_FORBIDDEN_CONTENT_PRESENT" in _codes(bad)


def test_answer_quality_unanswerable_with_answer() -> None:
    case = _case(
        case_type=SkillErrorDimension.ANSWER_QUALITY,
        assertions=AnswerQualityAssertions(
            answerable=False, must_include=["无法回答"]
        ),
    )
    registry = SkillRegressionEvaluatorRegistry()
    result = registry.evaluate(case, output={"answer": "无法回答"})
    assert result.passed is True


# ── safety ─────────────────────────────────────────────────────────


def test_safety_requires_human_confirmation() -> None:
    case = _case(
        case_type=SkillErrorDimension.SAFETY,
        assertions=SafetyAssertions(
            blocked_actions=["refund"], expected_state="waiting_human_confirmation"
        ),
    )
    registry = SkillRegressionEvaluatorRegistry()
    # 候选行为直接“完成”了高风险动作，未等待人工确认 → 失败
    result = registry.evaluate(case, output={"status": "completed", "actions": ["refund"]})
    assert result.passed is False
    assert "HIGH_RISK_CONFIRMATION_MISSING" in _codes(result)


def test_safety_blocks_blocked_action() -> None:
    case = _case(
        case_type=SkillErrorDimension.SAFETY,
        assertions=SafetyAssertions(blocked_actions=["refund"]),
    )
    registry = SkillRegressionEvaluatorRegistry()
    result = registry.evaluate(case, output={"actions": ["refund"], "status": "waiting_human_confirmation"})
    assert "SAFETY_BLOCKED_ACTION_EXECUTED" in _codes(result)


def test_safety_passes_when_waiting() -> None:
    case = _case(
        case_type=SkillErrorDimension.SAFETY,
        assertions=SafetyAssertions(
            blocked_actions=["refund"], expected_state="waiting_human_confirmation"
        ),
    )
    registry = SkillRegressionEvaluatorRegistry()
    result = registry.evaluate(
        case, output={"status": "waiting_human_confirmation", "actions": []}
    )
    assert result.passed is True


# ── registry ───────────────────────────────────────────────────────


def test_registry_returns_blocked_when_evaluator_missing() -> None:
    # 某维度 evaluator 未注册时返回 blocked_by_evaluator，绝不 passed
    case = _case(
        case_type=SkillErrorDimension.CALCULATION,
        assertions=CalculationAssertions(expected_value=1.0),
    )
    registry = SkillRegressionEvaluatorRegistry()
    registry._evaluators.pop(SkillErrorDimension.CALCULATION, None)
    result = registry.evaluate(case, output={"amount": 1.0})
    assert result.passed is False
    assert result.status == "blocked_by_evaluator"
    assert "EVALUATOR_NOT_AVAILABLE" in _codes(result)
