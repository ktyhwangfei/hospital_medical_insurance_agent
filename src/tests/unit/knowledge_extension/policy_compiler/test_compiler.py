from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.knowledge_extension.rule_explanation.policy_compiler.models import (
    CanonicalRule,
    CompileStep,
    PolicyExpression,
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
