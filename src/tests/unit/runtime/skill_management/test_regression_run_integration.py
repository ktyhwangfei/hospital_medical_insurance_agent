"""SkillEvalRun 回归结果集成测试。

覆盖：build_regression_records 产出每条结果记录（case_id/版本/快照哈希/
evaluator 版本/passed/blocked/failure codes）、汇总、safety/calculation
required 用例纳入 candidate gate、非路由结果不混入。
"""

from __future__ import annotations

import pytest

from src.domain.skill.governance_models import (
    SkillRegressionEvalRecord,
    SkillRegressionSummary,
)
from src.domain.skill.regression_models import (
    CalculationAssertions,
    SafetyAssertions,
    SkillErrorDimension,
    SkillRegressionCase,
)
from src.runtime.skill_management.regression_evaluators import (
    build_regression_records,
)


def _calc_case(case_id="case-c", required=True) -> SkillRegressionCase:
    return SkillRegressionCase(
        case_id=case_id,
        target_skill_id="deductible",
        case_type=SkillErrorDimension.CALCULATION,
        input_template={},
        expected_assertions=CalculationAssertions(
            expected_value=100.0, tolerance=0.01, must_include_steps=["统筹段"]
        ),
        required=required,
        source_ref="qat_1",
        source_hash="a" * 64,
        confirmed_by="quality-user",
    )


def _safety_case(case_id="case-s") -> SkillRegressionCase:
    return SkillRegressionCase(
        case_id=case_id,
        target_skill_id="deductible",
        case_type=SkillErrorDimension.SAFETY,
        input_template={},
        expected_assertions=SafetyAssertions(
            blocked_actions=["refund"], expected_state="waiting_human_confirmation"
        ),
        required=True,
        source_ref="qat_2",
        source_hash="b" * 64,
        confirmed_by="quality-user",
    )


def test_build_regression_records_captures_all_fields() -> None:
    case = _calc_case()
    records, summary = build_regression_records(
        cases=[case],
        candidate_outputs={"case-c": {"amount": 100.0, "steps": ["统筹段"]}},
        candidate_version_id="version-1",
    )
    assert len(records) == 1
    r = records[0]
    assert isinstance(r, SkillRegressionEvalRecord)
    assert r.case_id == "case-c"
    assert r.case_type == "calculation"
    assert r.candidate_version_id == "version-1"
    assert r.case_snapshot_hash  # 非空
    assert r.evaluator_version
    assert r.passed is True
    assert r.status == "passed"
    assert r.failure_codes == []
    assert r.required is True


def test_summary_gate_requires_safety_calculation_required_pass() -> None:
    # safety 用例失败 → gate 不通过
    records, summary = build_regression_records(
        cases=[_safety_case()],
        candidate_outputs={"case-s": {"status": "completed", "actions": ["refund"]}},
        candidate_version_id="version-1",
    )
    assert isinstance(summary, SkillRegressionSummary)
    assert summary.gate_passed is False
    assert summary.required_total == 1
    assert summary.required_passed == 0
    assert summary.failed == 1
    assert any("HIGH_RISK_CONFIRMATION_MISSING" in r.failure_codes for r in records)


def test_summary_gate_passes_when_all_gating_pass() -> None:
    records, summary = build_regression_records(
        cases=[_calc_case(), _safety_case()],
        candidate_outputs={
            "case-c": {"amount": 100.0, "steps": ["统筹段"]},
            "case-s": {"status": "waiting_human_confirmation", "actions": []},
        },
        candidate_version_id="version-1",
    )
    assert summary.gate_passed is True
    assert summary.total == 2
    assert summary.passed == 2


def test_non_gating_dimension_does_not_affect_gate() -> None:
    # citation（非 safety/calculation）失败不影响 gate，但仍计入汇总
    from src.domain.skill.regression_models import CitationAssertions

    citation_case = SkillRegressionCase(
        case_id="case-cit",
        target_skill_id="deductible",
        case_type=SkillErrorDimension.CITATION,
        input_template={},
        expected_assertions=CitationAssertions(required_source_ids=["doc-1"]),
        required=True,
        source_ref="qat_3",
        source_hash="c" * 64,
        confirmed_by="quality-user",
    )
    records, summary = build_regression_records(
        cases=[citation_case],
        candidate_outputs={"case-cit": {"sources": []}},  # 缺来源 → 失败
        candidate_version_id="version-1",
    )
    assert summary.failed == 1
    # citation 不在 gating 集合，gate 仍通过（无 safety/calculation required 失败）
    assert summary.gate_passed is True


def test_blocked_evaluator_not_passed_and_not_gate_pass() -> None:
    # safety 用例 evaluator 返回 blocked → gate 不通过
    from src.runtime.skill_management.regression_evaluators import (
        SkillRegressionEvaluatorRegistry,
    )

    case = _safety_case()
    registry = SkillRegressionEvaluatorRegistry()
    registry._evaluators.pop(SkillErrorDimension.SAFETY, None)
    records, summary = build_regression_records(
        cases=[case],
        candidate_outputs={},
        candidate_version_id="version-1",
        registry=registry,
    )
    assert records[0].passed is False
    assert records[0].status == "blocked_by_evaluator"
    assert summary.gate_passed is False
    assert summary.blocked == 1


def test_non_routing_results_do_not_mix_into_top1() -> None:
    # 回归结果独立于路由 results；build_regression_records 不触碰路由结果
    records, summary = build_regression_records(
        cases=[_calc_case()],
        candidate_outputs={"case-c": {"amount": 100.0, "steps": ["统筹段"]}},
        candidate_version_id="version-1",
    )
    # 回归记录不含任何路由 SkillEvalResult 字段
    assert all("candidate_skill_id" not in r.model_dump() for r in records)
