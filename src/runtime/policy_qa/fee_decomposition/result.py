"""SettlementDecompositionResult 对外 Pydantic 契约（设计 §11）。

金额对外统一十进制字符串；结构版本化（schema_version + algorithm_version）；
模型只可润色，不可改变数字及结论等级（answer_constraints 显式约束）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from src.runtime.policy_qa.fee_decomposition.fee_items import FeeItemExplanation
from src.runtime.policy_qa.fee_decomposition.explanation_evidence import ExplanationEvidence

from src.domain.insurance.fee_decomposition import (
    BranchOutcome,
    BranchTrace,
    CalculationRecord,
    CheckStatus,
    CheckType,
    DecompositionCitation,
    DecompositionUncertainty,
    ExplanationLevel,
    FieldReconciliation,
)

SCHEMA_VERSION = "1.0"
ALGORITHM_VERSION = "employee_outpatient_v1"


class DecompositionProfile(BaseModel):
    insurance_type: str
    medical_category: str


class BranchConditionModel(BaseModel):
    code: str
    description: str
    operator: str
    actual_value: str | None = None
    expected_ref: str | None = None


class BranchTraceModel(BaseModel):
    step_id: str
    module_id: str
    outcome: str
    parent_step_id: str | None = None
    scope_ref: str | None = None
    condition: BranchConditionModel | None = None
    reason_code: str | None = None
    input_refs: list[str] = []
    rule_refs: list[str] = []
    calculation_refs: list[str] = []


class CalculationOperandModel(BaseModel):
    ref: str
    value: str


class CalculationRecordModel(BaseModel):
    calculation_id: str
    formula_id: str
    formula_version: str
    operands: list[CalculationOperandModel] = []
    unrounded_result: str | None = None
    rounding_rule: str | None = None
    result: str | None = None


class FieldExplanationModel(BaseModel):
    field_code: str
    label: str
    check_type: str
    check_status: str
    observed_amount: str | None = None
    calculated_amount: str | None = None
    difference: str | None = None
    explanation_level: str
    reason_code: str | None = None
    calculation_refs: list[str] = []
    citation_refs: list[str] = []
    uncertainty_refs: list[str] = []


class CitationModel(BaseModel):
    id: str
    kind: str  # settlement_fact / fee_facts / issue_note / policy_document / source_catalog
    ref: str
    value: str | None = None
    values: list[str] = []
    approval_status: str | None = None


class UncertaintyModel(BaseModel):
    id: str
    code: str
    message: str
    affected_fields: list[str] = []


class CoverageSummary(BaseModel):
    target_field_count: int
    independently_explained_count: int
    amount_reconciled_count: int
    observed_only_count: int


class AnswerConstraints(BaseModel):
    may_claim_full_explanation: bool
    may_infer_missing_rules: bool = False


class SettlementDecompositionResult(BaseModel):
    """结算费用分解结构化结果（设计 §11）。"""

    schema_version: str = SCHEMA_VERSION
    fee_items: list[FeeItemExplanation] = Field(default_factory=list, exclude=True)
    explanation_evidence: ExplanationEvidence | None = Field(default=None, exclude=True)
    algorithm_version: str = ALGORITHM_VERSION
    settlement_ref: str
    profile: DecompositionProfile
    execution_status: str
    reconciliation_status: str
    fields: list[FieldExplanationModel] = []
    branches: list[BranchTraceModel] = []
    calculations: list[CalculationRecordModel] = []
    citations: list[CitationModel] = []
    uncertainties: list[UncertaintyModel] = []
    coverage: CoverageSummary
    answer_constraints: AnswerConstraints


# ── 领域值对象 → 契约模型转换 ──────────────────────────────────


def branch_to_model(b: BranchTrace) -> BranchTraceModel:
    return BranchTraceModel(
        step_id=b.step_id,
        module_id=b.module_id,
        outcome=b.outcome.value,
        parent_step_id=b.parent_step_id,
        scope_ref=b.scope_ref,
        condition=BranchConditionModel(
            code=b.condition.code,
            description=b.condition.description,
            operator=b.condition.operator,
            actual_value=b.condition.actual_value,
            expected_ref=b.condition.expected_ref,
        )
        if b.condition
        else None,
        reason_code=b.reason_code,
        input_refs=list(b.input_refs),
        rule_refs=list(b.rule_refs),
        calculation_refs=list(b.calculation_refs),
    )


def calc_to_model(c: CalculationRecord) -> CalculationRecordModel:
    return CalculationRecordModel(
        calculation_id=c.calculation_id,
        formula_id=c.formula_id,
        formula_version=c.formula_version,
        operands=[CalculationOperandModel(ref=o.ref, value=o.value) for o in c.operands],
        unrounded_result=c.unrounded_result,
        rounding_rule=c.rounding_rule,
        result=c.result,
    )


def field_to_model(f: FieldReconciliation) -> FieldExplanationModel:
    return FieldExplanationModel(
        field_code=f.field_code,
        label=f.label,
        check_type=f.check_type.value,
        check_status=f.check_status.value,
        observed_amount=f.observed_amount,
        calculated_amount=f.calculated_amount,
        difference=f.difference,
        explanation_level=f.explanation_level.value,
        reason_code=f.reason_code,
        calculation_refs=list(f.calculation_refs),
        citation_refs=list(f.citation_refs),
        uncertainty_refs=list(f.uncertainty_refs),
    )


def citation_to_model(c: DecompositionCitation) -> CitationModel:
    return CitationModel(
        id=c.id, kind=c.kind, ref=c.ref, value=c.value,
        values=list(c.values), approval_status=c.approval_status,
    )


def uncertainty_to_model(u: DecompositionUncertainty) -> UncertaintyModel:
    return UncertaintyModel(
        id=u.id, code=u.code, message=u.message, affected_fields=list(u.affected_fields),
    )


__all__ = [
    "AnswerConstraints",
    "BranchOutcome",
    "BranchTraceModel",
    "CalculationRecordModel",
    "CheckStatus",
    "CheckType",
    "CitationModel",
    "CoverageSummary",
    "ExplanationLevel",
    "FieldExplanationModel",
    "SettlementDecompositionResult",
    "branch_to_model",
    "calc_to_model",
    "citation_to_model",
    "field_to_model",
    "uncertainty_to_model",
]
