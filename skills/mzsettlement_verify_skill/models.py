"""门诊结算核验的严格内部模型。"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


MoneyState = Literal["non_zero", "reported_zero", "missing", "not_applicable"]
CheckStatus = Literal["passed", "failed", "not_evaluable"]
VerificationStatus = Literal["complete", "partial", "unavailable"]
MetricScalar = str | Decimal | int | bool | None


class OutpatientSettlementContext(BaseModel):
    """一笔门诊结算的公开业务语义，不包含物理字段名。"""

    total_amount: Decimal | None = None
    in_scope_amount: Decimal | None = None
    out_of_scope_amount: Decimal | None = None
    self_pay_one: Decimal | None = None
    self_pay_two: Decimal | None = None
    personal_total_amount: Decimal | None = None
    deductible_amount: Decimal | None = None
    beyond_cap_amount: Decimal | None = None
    large_self_pay: Decimal | None = None
    fund_total_amount: Decimal | None = None
    large_fund_payment: Decimal | None = None
    account_payment: Decimal | None = None
    cash_payment: Decimal | None = None
    big_disease_payment: Decimal | None = None
    retired_medical_payment: Decimal | None = None
    unit_supplement_payment: Decimal | None = None
    disabled_soldier_payment: Decimal | None = None
    supplementary_insurance_payment: Decimal | None = None
    assistance_payment: Decimal | None = None
    insurance_type: str | None = None
    person_type: str | None = None
    service_type: str | None = None
    hospital_level: str | None = None
    settlement_date: str | None = None
    record_found: bool | None = None
    applicability: dict[str, bool] = Field(default_factory=dict)
    additional_metrics: dict[str, MetricScalar] = Field(default_factory=dict)
    fee_items: list[dict[str, MetricScalar]] = Field(default_factory=list)
    data_quality_warnings: list[str] = Field(default_factory=list)


class PolicyEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_id: str
    rule_type: str | None = None
    payment_ratio: Decimal | None = None
    calculation_base: str | None = None
    benefit_type: str | None = None

    @field_validator("payment_ratio", mode="before")
    @classmethod
    def normalize_ratio(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return None
        return Decimal(text[:-1]) / 100 if text.endswith("%") else text


class AmountCheck(BaseModel):
    name: str
    equation: str
    # 数值算式（如 "90.00 元 = 75.60 元 + 14.40 元"），缺失时渲染层回退到实际/应得
    detail: str | None = None
    actual: Decimal | None
    expected: Decimal | None
    difference: Decimal | None
    tolerance: Decimal = Decimal("0.01")
    status: CheckStatus


class FieldExplanation(BaseModel):
    field_name: str
    value: Decimal | None
    state: MoneyState
    applicable: bool | None = None
    explanation: str
    citations: list[str] = Field(min_length=1)


class ContextCheck(BaseModel):
    name: str
    value: str | None
    status: Literal["present", "missing"]


class OutpatientVerificationResult(BaseModel):
    status: VerificationStatus
    scenario_id: str
    summary: str
    context_checks: list[ContextCheck] = Field(default_factory=list)
    amount_checks: list[AmountCheck] = Field(default_factory=list)
    field_explanations: list[FieldExplanation] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
