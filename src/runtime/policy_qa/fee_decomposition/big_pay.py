"""门诊大额支付与大额个人承担（设计 §7.4）。

按身份（在职/退休）、年龄档（<70/≥70，以交易日期算已满周岁）、机构（社区/其他）
选择基础比例档；2023-01-01 起无封顶、基金年度累计支付超 2 万段 60%；
2022-12-31 前适用 2 万元基金支付封顶（EOP-CAP-001）。

硬约束：
- 分段边界是**基金年度累计支付**口径（prior_fund_payment），不得用费用累计替代；
- 不得由账面 T_BigPay 反推适用比例（本模块不读取任何观测值）；
- 基金支付累计缺失或口径未确认 → unknown，不硬算；
- 大额个人承担 S = B - 大额支付；封顶以上个人承担的字段归属（T_BigSelfPay/T_BeyondBig）
  未确认，本模块只给出 S 总额并保留不确定性声明。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    BranchCondition,
    BranchOutcome,
    BranchTrace,
    CalculationOperand,
    CalculationRecord,
    DecompositionUncertainty,
    InstitutionKind,
    PersonKind,
    RoundingMode,
    apply_rounding,
    decimal_to_str,
)
from src.runtime.policy_qa.fee_decomposition.params_employee_outpatient import (
    select_big_pay_rate_param,
    select_cap_param,
    select_excess_segment_param,
)

MODULE_ID = "big_pay"

#: 超 2 万基金支付段边界（EOP-RATE-301/302：基金年度累计支付口径）
_EXCESS_FUND_THRESHOLD = Decimal("20000")
_NO_CAP_SINCE = date(2023, 1, 1)


@dataclass(frozen=True)
class PaySegment:
    """支付分段：基数、比例、支付额、规则引用。"""

    name: str  # base / excess_20k
    base_amount: Decimal
    ratio: Decimal
    pay: Decimal
    rule_id: str


@dataclass(frozen=True)
class BigPayResult:
    big_pay: Decimal | None  # 大额支付
    big_self_pay: Decimal | None  # S：大额共付段个人自付 = B - 大额支付
    segments: tuple[PaySegment, ...] = ()
    branches: tuple[BranchTrace, ...] = ()
    calculations: tuple[CalculationRecord, ...] = ()
    uncertainties: tuple[DecompositionUncertainty, ...] = ()


def full_age_at(birth_date: date, on_date: date) -> int:
    """以交易日期计算已满周岁（生日当日即满）。"""
    years = on_date.year - birth_date.year
    if (on_date.month, on_date.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def decompose_big_pay(
    copay_base: Decimal | None,
    person_kind: PersonKind,
    birth_date: date | None,
    institution_kind: InstitutionKind,
    settlement_date: date,
    prior_fund_payment: Decimal | None,
    prior_fund_is_pre_trade_confirmed: bool,
    rounding_mode: RoundingMode,
) -> BigPayResult:
    """大额支付分解纯函数。"""
    branches: list[BranchTrace] = []
    calcs: list[CalculationRecord] = []
    uncertainties: list[DecompositionUncertainty] = []

    if copay_base is None:
        branches.append(BranchTrace(
            step_id="big_pay.base_available", module_id=MODULE_ID, scope_ref="trade",
            condition=BranchCondition("copay_base", "共付段基数可用性", "not_null", None, "B"),
            outcome=BranchOutcome.BLOCKED, reason_code="UPSTREAM_BASE_MISSING",
            input_refs=("calc.deductible.split",),
        ))
        uncertainties.append(DecompositionUncertainty(
            id="u.big_pay.base", code="UPSTREAM_BASE_MISSING",
            message="起付线分解未得出共付段基数，大额支付阻断。",
            affected_fields=("T_BigPay", "T_BigSelfPay")))
        return BigPayResult(None, None, (), tuple(branches), (), tuple(uncertainties))

    # 年龄档（仅退休需要；在职不评估年龄分支）
    age_band: str | None = None
    if person_kind == PersonKind.RETIRED:
        if birth_date is None:
            branches.append(BranchTrace(
                step_id="big_pay.age_band", module_id=MODULE_ID, scope_ref="trade",
                condition=BranchCondition("age_band", "退休年龄档（已满70周岁）", "ge", None, "70"),
                outcome=BranchOutcome.UNKNOWN, reason_code="BIRTH_DATE_MISSING",
                input_refs=("fact.person.birth_date",)))
            uncertainties.append(DecompositionUncertainty(
                id="u.big_pay.age_band", code="BIRTH_DATE_MISSING",
                message="缺少出生日期，退休大额支付年龄档（<70/≥70）不能确定。",
                affected_fields=("T_BigPay", "T_BigSelfPay")))
            return BigPayResult(None, None, (), tuple(branches), (), tuple(uncertainties))
        age = full_age_at(birth_date, settlement_date)
        age_band = "ge70" if age >= 70 else "lt70"
        branches.append(BranchTrace(
            step_id="big_pay.age_band", module_id=MODULE_ID, scope_ref="trade",
            condition=BranchCondition("age_band", "退休年龄档（已满70周岁）", "ge", str(age), "70"),
            outcome=BranchOutcome.TRUE if age >= 70 else BranchOutcome.FALSE,
            input_refs=("fact.person.birth_date", "fact.trade.trade_date")))
        if (birth_date.month, birth_date.day) == (2, 29):
            uncertainties.append(DecompositionUncertainty(
                id="u.big_pay.leap_day", code="AGE_LEAP_DAY_CALIBER_UNCONFIRMED",
                message="出生日期为 2 月 29 日，非闰年生日口径未确认。",
                affected_fields=("T_BigPay",)))
    else:
        branches.append(BranchTrace(
            step_id="big_pay.age_band", module_id=MODULE_ID, scope_ref="trade",
            condition=BranchCondition("age_band", "退休年龄档（已满70周岁）", "ge", None, "70"),
            outcome=BranchOutcome.NOT_EVALUATED, reason_code="NOT_RETIRED"))

    # 基础支付比例选择（合计展示层次不在候选内）
    sel = select_big_pay_rate_param(person_kind, age_band, institution_kind, settlement_date)
    branches.append(BranchTrace(
        step_id="big_pay.rate_select", module_id=MODULE_ID, scope_ref="trade",
        condition=BranchCondition("big_pay_rate", "大额基础支付比例档选择", "select",
                                  f"{person_kind.value}/{age_band}/{institution_kind.value}",
                                  "EOP-RATE-1xx 基础支付档"),
        outcome=sel.outcome, reason_code=sel.reason_code,
        input_refs=("fact.person.person_type_code", "fact.institution.h_level"),
        rule_refs=("EOP-RATE-105", "EOP-RATE-106", "EOP-RATE-110", "EOP-RATE-111", "EOP-RATE-112")))
    if sel.outcome != BranchOutcome.TRUE or sel.param is None or sel.param.ratio is None:
        uncertainties.append(DecompositionUncertainty(
            id="u.big_pay.rate", code=sel.reason_code or "PARAM_VERSION_NOT_FOUND",
            message="适用大额支付比例档不能确定，不采用默认比例。",
            affected_fields=("T_BigPay", "T_BigSelfPay")))
        return BigPayResult(None, None, (), tuple(branches), (), tuple(uncertainties))
    base_rate = sel.param.ratio
    base_rule_id = sel.param.rule_id

    # 基金支付累计：封顶与超 2 万段切档的共同前提（基金支付口径）
    if prior_fund_payment is None or not prior_fund_is_pre_trade_confirmed:
        branches.append(BranchTrace(
            step_id="big_pay.fund_cumulative", module_id=MODULE_ID, scope_ref="trade",
            condition=BranchCondition("prior_fund_payment", "交易前基金年度累计支付可用且口径已确认",
                                      "confirmed",
                                      decimal_to_str(prior_fund_payment) if prior_fund_payment is not None else None,
                                      "基金支付累计（交易前）"),
            outcome=BranchOutcome.UNKNOWN,
            reason_code="FUND_CUMULATIVE_MISSING" if prior_fund_payment is None
            else "FUND_CUMULATIVE_CALIBER_UNCONFIRMED",
            input_refs=("fact.trade.prior_fund_payment",)))
        uncertainties.append(DecompositionUncertainty(
            id="u.big_pay.fund_cumulative", code=branches[-1].reason_code or "FUND_CUMULATIVE_MISSING",
            message="缺少交易前基金支付累计（或口径未确认），封顶/超 2 万段切档不能确定。",
            affected_fields=("T_BigPay", "T_BigSelfPay")))
        return BigPayResult(None, None, (), tuple(branches), (), tuple(uncertainties))

    segments: list[PaySegment] = []
    if settlement_date < _NO_CAP_SINCE:
        # 2022-12-31 前：2 万元基金支付封顶（EOP-CAP-001）
        cap_sel = select_cap_param(settlement_date)
        branches.append(BranchTrace(
            step_id="big_pay.cap_regime", module_id=MODULE_ID, scope_ref="trade",
            condition=BranchCondition("cap_regime", "基金支付封顶规则适用", "select",
                                      settlement_date.isoformat(), "EOP-CAP-001"),
            outcome=cap_sel.outcome, reason_code=cap_sel.reason_code,
            rule_refs=("EOP-CAP-001",)))
        if cap_sel.outcome != BranchOutcome.TRUE or cap_sel.param is None or cap_sel.param.value is None:
            uncertainties.append(DecompositionUncertainty(
                id="u.big_pay.cap", code=cap_sel.reason_code or "PARAM_VERSION_NOT_FOUND",
                message="基金支付封顶规则不能确定。", affected_fields=("T_BigPay", "T_BigSelfPay")))
            return BigPayResult(None, None, (), tuple(branches), (), tuple(uncertainties))
        cap = cap_sel.param.value
        fund_room = max(cap - prior_fund_payment, Decimal("0"))
        raw = copay_base * base_rate
        pay_unrounded = min(raw, fund_room)
        pay = apply_rounding(pay_unrounded, rounding_mode)
        calcs.append(CalculationRecord(
            calculation_id="calc.big_pay.capped", formula_id="big_pay_capped_v1", formula_version="v1",
            operands=(
                CalculationOperand("calc.deductible.copay_base", decimal_to_str(copay_base)),
                CalculationOperand(f"rule.{base_rule_id}", decimal_to_str(base_rate)),
                CalculationOperand("fact.trade.prior_fund_payment", decimal_to_str(prior_fund_payment)),
                CalculationOperand(f"rule.{cap_sel.param.rule_id}", decimal_to_str(cap)),
            ),
            unrounded_result=decimal_to_str(pay_unrounded),
            rounding_rule=f"explicit:{rounding_mode.value}(EOP-RND-001 待确认)",
            result=decimal_to_str(pay)))
        segments.append(PaySegment("base", copay_base, base_rate, pay, base_rule_id))
        if raw > fund_room:
            uncertainties.append(DecompositionUncertainty(
                id="u.big_pay.beyond_cap_attribution", code="BEYOND_CAP_FIELD_ATTRIBUTION_UNCONFIRMED",
                message="存在封顶以上费用；其个人承担归属字段（T_BigSelfPay/T_BeyondBig）未确认，未自动归入大额自付。",
                affected_fields=("T_BigSelfPay",)))
    else:
        # 2023-01-01 起：无封顶，基金累计支付超 2 万段 60%（EOP-RATE-301/302）
        branches.append(BranchTrace(
            step_id="big_pay.cap_regime", module_id=MODULE_ID, scope_ref="trade",
            condition=BranchCondition("cap_regime", "基金支付封顶规则适用", "select",
                                      settlement_date.isoformat(), "EOP-CAP-001"),
            outcome=BranchOutcome.FALSE, reason_code="CAP_ABOLISHED_FROM_2023",
            rule_refs=("EOP-CAP-001", "EOP-RATE-301", "EOP-RATE-302")))
        excess_sel = select_excess_segment_param(person_kind, settlement_date)
        if excess_sel.outcome != BranchOutcome.TRUE or excess_sel.param is None or excess_sel.param.ratio is None:
            uncertainties.append(DecompositionUncertainty(
                id="u.big_pay.excess_rate", code=excess_sel.reason_code or "PARAM_VERSION_NOT_FOUND",
                message="超 2 万段支付比例不能确定。", affected_fields=("T_BigPay", "T_BigSelfPay")))
            return BigPayResult(None, None, (), tuple(branches), (), tuple(uncertainties))
        excess_rate = excess_sel.param.ratio
        # 基金口径边界换算为本次费用口径：B1 = (20000 - 交易前基金累计) / 基础比例
        # （仅在本段内基础比例恒定时成立；逐段边界与取整过程见计算记录）
        below_room = max(_EXCESS_FUND_THRESHOLD - prior_fund_payment, Decimal("0"))
        b1 = min(copay_base, below_room / base_rate)
        b2 = copay_base - b1
        pay1 = apply_rounding(b1 * base_rate, rounding_mode)
        pay2 = apply_rounding(b2 * excess_rate, rounding_mode)
        pay = pay1 + pay2
        calcs.append(CalculationRecord(
            calculation_id="calc.big_pay.segmented", formula_id="big_pay_segmented_v1", formula_version="v1",
            operands=(
                CalculationOperand("calc.deductible.copay_base", decimal_to_str(copay_base)),
                CalculationOperand(f"rule.{base_rule_id}", decimal_to_str(base_rate)),
                CalculationOperand("fact.trade.prior_fund_payment", decimal_to_str(prior_fund_payment)),
                CalculationOperand(f"rule.{excess_sel.param.rule_id}", decimal_to_str(excess_rate)),
            ),
            unrounded_result=decimal_to_str(b1 * base_rate + b2 * excess_rate),
            rounding_rule=f"explicit:{rounding_mode.value}(EOP-RND-001 待确认；逐段取整层级待确认)",
            result=decimal_to_str(pay)))
        segments.append(PaySegment("base", b1, base_rate, pay1, base_rule_id))
        if b2 > 0:
            segments.append(PaySegment("excess_20k", b2, excess_rate, pay2, excess_sel.param.rule_id))

    big_self_pay = copay_base - pay
    calcs.append(CalculationRecord(
        calculation_id="calc.big_pay.self_pay", formula_id="big_self_pay_v1", formula_version="v1",
        operands=(
            CalculationOperand("calc.deductible.copay_base", decimal_to_str(copay_base)),
            CalculationOperand("calc.big_pay", decimal_to_str(pay)),
        ),
        unrounded_result=decimal_to_str(big_self_pay),
        rounding_rule="not_applicable（减法运算，无取整）",
        result=decimal_to_str(big_self_pay)))
    branches.append(BranchTrace(
        step_id="big_pay.settle", module_id=MODULE_ID, scope_ref="trade",
        condition=BranchCondition("big_pay_settle", "大额支付=Σ各段基数×比例（受封顶约束）", "formula",
                                  decimal_to_str(pay), None),
        outcome=BranchOutcome.TRUE,
        rule_refs=tuple(seg.rule_id for seg in segments),
        calculation_refs=tuple(c.calculation_id for c in calcs)))
    return BigPayResult(pay, big_self_pay, tuple(segments), tuple(branches), tuple(calcs), tuple(uncertainties))
