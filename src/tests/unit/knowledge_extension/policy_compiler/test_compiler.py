from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.knowledge_extension.rule_explanation.policy_compiler.compiler import (
    PolicyRuleCompiler,
)
from src.knowledge_extension.rule_explanation.policy_compiler.models import (
    CanonicalRule,
    CompileStep,
    PolicyExpression,
    PolicyFact,
)


def fact(
    fact_id: str,
    *,
    subject: str = "personal_payment_ratio",
    population: str | None = None,
    conditions: dict | None = None,
    ratio: str | None = None,
    amount: str | None = None,
    expression: dict | None = None,
) -> PolicyFact:
    value = {}
    if ratio is not None:
        value["ratio"] = ratio
    if amount is not None:
        value["amount"] = amount
    return PolicyFact(
        fact_id=fact_id,
        subject=subject,
        population=population,
        conditions=conditions or {},
        value=value,
        expression=expression,
        evidence=[f"evidence_{fact_id}"],
    )


def test_compile_stage_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        CompileStep(
            step_id="step_1",
            run_id="run_1",
            sequence_no=1,
            stage="GUESS",
            status="PASS",
        )


def test_multiply_expression_rejects_out_of_range_factor() -> None:
    with pytest.raises(ValidationError):
        PolicyExpression(operator="MULTIPLY", factor=Decimal("1.2"))


def test_rule_rejects_ratio_above_one() -> None:
    with pytest.raises(ValidationError):
        CanonicalRule(
            rule_id="rule_1",
            subject="personal_payment_ratio",
            result={"ratio": Decimal("1.01")},
            evidence=["evidence_1"],
        )


def test_rule_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        CanonicalRule(
            rule_id="rule_1",
            subject="personal_payment_ratio",
            result={"ratio": Decimal("0.1")},
            evidence=[],
        )


@pytest.mark.parametrize(
    ("dependencies", "formula"),
    [
        ([], PolicyExpression(operator="MULTIPLY", factor=Decimal("0.6"))),
        (["rule_base"], None),
    ],
)
def test_derived_rule_requires_dependency_and_formula(
    dependencies: list[str], formula: PolicyExpression | None
) -> None:
    with pytest.raises(ValidationError):
        CanonicalRule(
            rule_id="rule_1",
            subject="personal_payment_ratio",
            source_type="DERIVED",
            result={"ratio": Decimal("0.09")},
            evidence=["evidence_1"],
            dependencies=dependencies,
            formula=formula,
        )


def test_relative_ratio_is_resolved_and_derived_without_policy_constants() -> None:
    facts = [
        fact(
            "base_a",
            population="employee",
            conditions={"hospital_level": "tertiary", "amount_band": "0-30000"},
            ratio="0.15",
        ),
        fact(
            "base_b",
            population="employee",
            conditions={"hospital_level": "tertiary", "amount_band": "30000-40000"},
            ratio="0.10",
        ),
        fact(
            "relative",
            population="retiree",
            expression={
                "operator": "MULTIPLY",
                "reference": {
                    "population": "employee",
                    "subject": "personal_payment_ratio",
                },
                "factor": "0.75",
            },
        ),
    ]

    result = PolicyRuleCompiler().compile(facts)

    assert [
        rule.result["ratio"]
        for rule in result.rules
        if rule.source_type == "DERIVED"
    ] == [Decimal("0.1125"), Decimal("0.0750")]
    assert result.status == "PASS"


def test_multiply_expression_is_reused_for_admission_order_amount() -> None:
    result = PolicyRuleCompiler().compile([
        fact(
            "first_admission",
            subject="deductible_line",
            conditions={"admission_order": "first"},
            amount="1200",
        ),
        fact(
            "next_admission",
            subject="deductible_line",
            conditions={"admission_order": "subsequent"},
            expression={
                "operator": "MULTIPLY",
                "reference": {
                    "subject": "deductible_line",
                    "admission_order": "first",
                },
                "factor": "0.4",
            },
        ),
    ])

    derived = next(rule for rule in result.rules if rule.source_type == "DERIVED")
    assert derived.result == {"amount": Decimal("480.0")}
    assert derived.dependencies
    assert derived.formula == PolicyExpression(
        operator="MULTIPLY",
        reference={"subject": "deductible_line", "admission_order": "first"},
        factor=Decimal("0.4"),
    )


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (
            {"operator": "COMPLEMENT", "reference": {"population": "employee"}, "total": "1"},
            Decimal("0.8"),
        ),
        (
            {"operator": "DIRECT_COPY", "reference": {"population": "employee"}},
            Decimal("0.2"),
        ),
    ],
)
def test_other_v1_operators_are_deterministic(
    expression: dict, expected: Decimal
) -> None:
    result = PolicyRuleCompiler().compile([
        fact("base", population="employee", ratio="0.2"),
        fact("derived", population="retiree", expression=expression),
    ])

    derived = next(rule for rule in result.rules if rule.source_type == "DERIVED")
    assert derived.result["ratio"] == expected
    assert result.status == "PASS"


@pytest.mark.parametrize(
    ("facts", "code"),
    [
        (
            [
                fact(
                    "relative",
                    population="retiree",
                    expression={
                        "operator": "MULTIPLY",
                        "reference": {"population": "employee"},
                        "factor": "0.6",
                    },
                )
            ],
            "NOT_FOUND",
        ),
        (
            [
                fact("base_a", population="employee", conditions={"hospital_level": "one"}, ratio="0.1"),
                fact("base_b", population="employee", conditions={"hospital_level": "two"}, ratio="0.2"),
                fact(
                    "relative",
                    population="retiree",
                    expression={
                        "operator": "MULTIPLY",
                        "reference": {"population": "employee"},
                        "factor": "0.6",
                    },
                ),
            ],
            "AMBIGUOUS",
        ),
        (
            [
                fact("duplicate_a", population="employee", ratio="0.1"),
                fact("duplicate_b", population="employee", ratio="0.2"),
            ],
            "CONFLICT",
        ),
        ([fact("invalid_ratio", ratio="120")], "RATIO_OUT_OF_RANGE"),
        (
            [
                fact("band_a", conditions={"amount_band": "0-30000"}, ratio="0.1"),
                fact("band_b", conditions={"amount_band": "20000-40000"}, ratio="0.2"),
            ],
            "AMOUNT_BAND_OVERLAP",
        ),
    ],
)
def test_compiler_reports_stable_issue_codes(
    facts: list[PolicyFact], code: str
) -> None:
    result = PolicyRuleCompiler().compile(facts)

    assert code in {issue.code for issue in result.issues}
    assert result.status in {"REVIEW", "FAIL"}


def test_compiler_reports_missing_evidence() -> None:
    mutated = PolicyFact.model_construct(
        fact_id="missing_evidence",
        subject="personal_payment_ratio",
        population=None,
        conditions={},
        value={"ratio": "0.1"},
        expression=None,
        evidence=[],
        document_id=None,
        unit_id=None,
        extraction_id=None,
        confidence=None,
    )

    result = PolicyRuleCompiler().compile([mutated])

    assert "EVIDENCE_REQUIRED" in {issue.code for issue in result.issues}
    assert result.status == "FAIL"


def test_compile_steps_are_ordered_and_capture_snapshots() -> None:
    result = PolicyRuleCompiler().compile([fact("base", ratio="0.1")], run_id="run_x")

    assert [step.stage for step in result.steps] == [
        "CANONICALIZE",
        "COMPOSE",
        "RESOLVE",
        "DERIVE",
        "VALIDATE",
    ]
    assert [step.sequence_no for step in result.steps] == [1, 2, 3, 4, 5]
    assert all(step.run_id == "run_x" for step in result.steps)
    assert all(step.input_payload or step.output_payload for step in result.steps)


@pytest.mark.parametrize(
    "subject",
    ["unclassified", "unknown", "未分类", " ", "UNCLASSIFIED", "none"],
)
def test_compiler_rejects_subject_sentinel(subject: str) -> None:
    """身份无法确定的规则必须 fail-closed，禁止塌缩进同一条 rule_id。

    复现 rule_8f94f240d5da7fb6：dummy 提取产出 subject=unclassified，导致 25 条
    语义不同的规则算出同一 rule_id。哨兵值必须在 Canonicalize 阶段直接拦截。
    """
    result = PolicyRuleCompiler().compile([fact("k", subject=subject, ratio="0.3")])

    assert "SUBJECT_MISSING" in {issue.code for issue in result.issues}
    assert result.status == "FAIL"
    assert result.rules == []


def test_rule_key_distinguishes_result_dimensions() -> None:
    """同 subject/population 但结果维度不同（比例 vs 金额）必须产生独立 rule_id。

    rule_key 此前不含 result 维度，导致“退休人员的比例”与“退休人员的金额”
    在 subject 撞名时塌缩。补 value.keys() 后必须分离。
    """
    facts = [
        fact("ratio_rule", population="retiree", ratio="0.3"),
        fact("amount_rule", population="retiree", amount="1200"),
    ]

    result = PolicyRuleCompiler().compile(facts)

    assert result.status == "PASS"
    assert len({rule.rule_id for rule in result.rules}) == 2
