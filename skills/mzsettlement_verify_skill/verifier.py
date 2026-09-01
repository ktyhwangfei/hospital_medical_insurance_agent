"""只执行有明确业务含义和证据前提的确定性门诊结算核验。"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from .models import (
    AmountCheck,
    ContextCheck,
    FieldExplanation,
    MoneyState,
    OutpatientSettlementContext,
    OutpatientVerificationResult,
    PolicyEvidence,
)


CENT = Decimal("0.01")
MONEY_FIELDS = (
    ("total_amount", "费用总金额"),
    ("in_scope_amount", "医保范围内金额"),
    ("self_pay_one", "个人自付一"),
    ("deductible_amount", "起付金额"),
    ("beyond_cap_amount", "超封顶金额"),
    ("account_payment", "个人账户支付"),
    ("cash_payment", "现金支付"),
    ("big_disease_payment", "大病支付"),
    ("retired_medical_payment", "退役医疗支付"),
    ("unit_supplement_payment", "单位补充医疗支付"),
    ("personal_total_amount", "个人支付总金额"),
    ("out_of_scope_amount", "医保范围外金额"),
    ("self_pay_two", "个人自付二"),
    ("large_self_pay", "大额自付"),
    ("fund_total_amount", "基金支付总金额"),
    ("large_fund_payment", "门诊大额基金支付"),
    ("disabled_soldier_payment", "军残补助支付"),
    ("supplementary_insurance_payment", "补充保险支付"),
    ("assistance_payment", "医疗救助支付"),
)


def money(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def state_of(value: object, *, applicable: bool | None = None) -> MoneyState:
    if applicable is False:
        return "not_applicable"
    amount = money(value)
    if amount is None:
        return "missing"
    return "reported_zero" if amount == 0 else "non_zero"


def _amount_check(name: str, equation: str, actual: object, expected: object) -> AmountCheck:
    actual_amount = money(actual)
    expected_amount = money(expected)
    if actual_amount is None or expected_amount is None:
        return AmountCheck(
            name=name, equation=equation, actual=actual_amount, expected=expected_amount,
            difference=None, status="not_evaluable",
        )
    difference = (actual_amount - expected_amount).quantize(CENT)
    return AmountCheck(
        name=name, equation=equation, actual=actual_amount, expected=expected_amount,
        difference=difference,
        status="passed" if abs(difference) <= CENT else "failed",
    )


def verify_settlement(
    context: OutpatientSettlementContext,
    *,
    scenario_id: str = "overall-settlement-verification",
    policy_evidence: list[dict] | None = None,
    money_fields: set[str] | None = None,
    required_money_fields: set[str] | None = None,
) -> OutpatientVerificationResult:
    """核验一笔门诊结算；证据不足时只陈述事实，不猜政策公式。"""
    evidence = [PolicyEvidence.model_validate(item) for item in (policy_evidence or [])]
    checks: list[AmountCheck] = []
    if context.in_scope_amount is not None and context.out_of_scope_amount is not None:
        checks.append(_amount_check(
            "总费用医保内外勾稽", "费用总金额 = 医保范围内金额 + 医保范围外金额",
            context.total_amount, context.in_scope_amount + context.out_of_scope_amount,
        ))
    if context.fund_total_amount is not None and context.personal_total_amount is not None:
        checks.append(_amount_check(
            "总费用支付方勾稽", "费用总金额 = 基金支付总金额 + 个人支付总金额",
            context.total_amount, context.fund_total_amount + context.personal_total_amount,
        ))
    self_pay_two_items = [
        money(item.get("FeeItem_SelfPay2"))
        for item in context.fee_items
        if item.get("FeeItem_SelfPay2") is not None
    ]
    if self_pay_two_items:
        checks.append(_amount_check(
            "个人自付二明细勾稽",
            "个人自付二 = 各费用明细先自付金额之和",
            context.self_pay_two,
            sum(self_pay_two_items, Decimal("0.00")),
        ))
    if context.account_payment is not None and context.cash_payment is not None:
        checks.append(_amount_check(
            "个人支付渠道勾稽", "个人支付总金额 = 个人账户支付 + 现金支付",
            context.personal_total_amount, context.account_payment + context.cash_payment,
        ))
    ratio_rule = next(
        (
            item for item in evidence
            if item.payment_ratio is not None
            and item.calculation_base == "in_scope_minus_deductible"
        ),
        None,
    )
    if ratio_rule and context.in_scope_amount is not None and context.deductible_amount is not None:
        checks.append(_amount_check(
            "门诊大额基金支付比例",
            "门诊大额基金支付 = (医保范围内金额 - 起付金额) × 政策支付比例",
            context.large_fund_payment,
            (context.in_scope_amount - context.deductible_amount) * ratio_rule.payment_ratio,
        ))

    evidence_ids = list(dict.fromkeys(item.source_id for item in evidence))
    field_explanations = []
    fields_to_explain = MONEY_FIELDS if money_fields is None else (
        item for item in MONEY_FIELDS if item[0] in money_fields
    )
    for field, label in fields_to_explain:
        value = getattr(context, field)
        applicable = context.applicability.get(field)
        state = state_of(value, applicable=applicable)
        explanations = {
            "non_zero": f"结算数据明确记录了{label}。",
            "reported_zero": f"结算数据明确记录{label}为 0 元，不能仅据此推断无待遇资格。",
            "missing": f"结算数据未返回{label}。",
            "not_applicable": f"结算资格事实标记{label}不适用。",
        }
        field_explanations.append(FieldExplanation(
            field_name=label,
            value=money(value),
            state=state,
            applicable=applicable,
            explanation=explanations[state],
            citations=[
                "settlement-data",
                *(evidence_ids if state == "not_applicable" else []),
            ],
        ))
    uncertainties: list[str] = []
    uncertainties.extend(context.data_quality_warnings)
    if not evidence:
        uncertainties.append("未提供适用于本次结算的人群、险种、机构和日期政策证据。")
    if money(context.unit_supplement_payment) not in {None, Decimal("0.00")} and not any(
        item.benefit_type == "单位补充医疗" for item in evidence
    ):
        uncertainties.append("单位补充医疗支付有实际金额，但缺少单位补充政策公式。")
    if any(item.state == "missing" for item in field_explanations):
        uncertainties.append("部分结算字段缺失，未将缺失值按 0 元处理。")

    context_checks = [
        ContextCheck(
            name=label,
            value=getattr(context, field),
            status="present" if getattr(context, field) is not None else "missing",
        )
        for field, label in (
            ("insurance_type", "险种"),
            ("person_type", "人员类别"),
            ("service_type", "医疗类别"),
            ("hospital_level", "医疗机构等级"),
            ("settlement_date", "结算日期"),
        )
    ]
    if any(item.status == "missing" for item in context_checks):
        uncertainties.append("部分待遇适用上下文缺失，不能据此确认政策是否适用。")

    anomalies = [
        f"{item.name}差额为 {item.difference} 元。"
        for item in checks if item.status == "failed"
    ]
    required_fields = {"total_amount"} if required_money_fields is None else required_money_fields
    core_amount_missing = any(getattr(context, field) is None for field in required_fields)
    if context.record_found is False or core_amount_missing:
        status = "unavailable"
    elif anomalies or uncertainties:
        status = "partial"
    else:
        status = "complete"
    return OutpatientVerificationResult(
        status=status,
        scenario_id=scenario_id,
        summary=(
            "结算记录或场景核心金额不可用。" if status == "unavailable"
            else "金额勾稽存在差异，需人工复核。" if anomalies
            else "已完成可用门诊结算金额勾稽。"
        ),
        context_checks=context_checks,
        amount_checks=checks,
        field_explanations=field_explanations,
        anomalies=anomalies,
        citations=evidence_ids,
        uncertainties=uncertainties,
        next_actions=["请医保经办人员核对原始结算单和适用政策。"] if anomalies or uncertainties else [],
    )
