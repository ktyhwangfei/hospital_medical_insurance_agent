"""居民门诊大额支付与大额个人承担（Issue #80）。

结构：单段支付比例（按机构等级档 55%/50%）+ 基金年度封顶（4500 元，2021-01-01 起）。
与职工 big_pay 的差异：无在职/退休与年龄档维度、无超 2 万分段、封顶不废止。

正负交易统一 clamp（mz.docx 居民§退费，ROP-REF-001/002）：

    pay = clamp(round(B × rate), −prior_fund, max(cap − prior_fund, 0))

- 正向：不超过封顶剩余额度（cap − 交易前基金累计）；
- 退费（B<0）：退还不超过交易前已付基金累计（−prior_fund 为下界）；
- 大额个人承担 S = B − pay（共付段个人自付）。

硬约束：
- 分段边界是**基金年度累计支付**口径（prior_fund_payment），不得用费用累计替代；
- 不得由账面 T_BigPay 反推适用比例（本模块不读取任何观测值）；
- 基金支付累计缺失或口径未确认 → unknown，不硬算。
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
    InstitutionLevelTier,
    RoundingMode,
    apply_rounding,
    decimal_to_str,
)
from src.runtime.policy_qa.fee_decomposition.params_resident_outpatient import (
    select_resident_big_pay_rate_param,
    select_resident_cap_param,
)

MODULE_ID = "resident_big_pay"


@dataclass(frozen=True)
class ResidentBigPayResult:
    big_pay: Decimal | None  # 大额基金支付（退费为负）
    big_self_pay: Decimal | None  # S：大额共付段个人自付 = B − 大额支付
    branches: tuple[BranchTrace, ...] = ()
    calculations: tuple[CalculationRecord, ...] = ()
    uncertainties: tuple[DecompositionUncertainty, ...] = ()


def decompose_resident_big_pay(
    copay_base: Decimal | None,
    institution_tier: InstitutionLevelTier,
    settlement_date: date,
    prior_fund_payment: Decimal | None,
    prior_fund_is_pre_trade_confirmed: bool,
    rounding_mode: RoundingMode,
) -> ResidentBigPayResult:
    """居民大额支付分解纯函数（支持正向与退费交易）。"""
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
        return ResidentBigPayResult(None, None, tuple(branches), (), tuple(uncertainties))

    # 基础支付比例选择（按机构等级档 + 结算日期）
    sel = select_resident_big_pay_rate_param(institution_tier, settlement_date)
    branches.append(BranchTrace(
        step_id="big_pay.rate_select", module_id=MODULE_ID, scope_ref="trade",
        condition=BranchCondition("big_pay_rate", "大额基础支付比例档选择", "select",
                                  f"{institution_tier.value}@{settlement_date.isoformat()}",
                                  "ROP-RATE-001/002（历史 101/102）"),
        outcome=sel.outcome, reason_code=sel.reason_code,
        input_refs=("fact.institution.h_level",),
        rule_refs=("ROP-RATE-001", "ROP-RATE-002", "ROP-RATE-101", "ROP-RATE-102")))
    if sel.outcome != BranchOutcome.TRUE or sel.param is None or sel.param.ratio is None:
        uncertainties.append(DecompositionUncertainty(
            id="u.big_pay.rate", code=sel.reason_code or "PARAM_VERSION_NOT_FOUND",
            message="适用大额支付比例档不能确定，不采用默认比例。",
            affected_fields=("T_BigPay", "T_BigSelfPay")))
        return ResidentBigPayResult(None, None, tuple(branches), (), tuple(uncertainties))
    base_rate = sel.param.ratio
    base_rule_id = sel.param.rule_id

    # 封顶线版本选择（按结算日期：3000→4000→4500）
    cap_sel = select_resident_cap_param(settlement_date)
    branches.append(BranchTrace(
        step_id="big_pay.cap_regime", module_id=MODULE_ID, scope_ref="trade",
        condition=BranchCondition("cap_regime", "基金支付封顶规则适用", "select",
                                  settlement_date.isoformat(), "ROP-CAP-001/002/003"),
        outcome=cap_sel.outcome, reason_code=cap_sel.reason_code,
        rule_refs=("ROP-CAP-001", "ROP-CAP-002", "ROP-CAP-003")))
    if cap_sel.outcome != BranchOutcome.TRUE or cap_sel.param is None or cap_sel.param.value is None:
        uncertainties.append(DecompositionUncertainty(
            id="u.big_pay.cap", code=cap_sel.reason_code or "PARAM_VERSION_NOT_FOUND",
            message="基金支付封顶规则不能确定。", affected_fields=("T_BigPay", "T_BigSelfPay")))
        return ResidentBigPayResult(None, None, tuple(branches), (), tuple(uncertainties))
    cap = cap_sel.param.value

    # 基金支付累计：封顶与退费下界切档的共同前提（基金支付口径）
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
            message="缺少交易前基金支付累计（或口径未确认），封顶/退费下界切档不能确定。",
            affected_fields=("T_BigPay", "T_BigSelfPay")))
        return ResidentBigPayResult(None, None, tuple(branches), (), tuple(uncertainties))

    # pay = clamp(round(B×rate), −prior_fund, max(cap−prior_fund, 0))
    upper = max(cap - prior_fund_payment, Decimal("0"))
    lower = -prior_fund_payment
    raw_unrounded = copay_base * base_rate
    raw = apply_rounding(raw_unrounded, rounding_mode)
    pay = min(max(raw, lower), upper)
    calcs.append(CalculationRecord(
        calculation_id="calc.big_pay.cap_room", formula_id="cap_room_v1", formula_version="v1",
        operands=(
            CalculationOperand(f"rule.{cap_sel.param.rule_id}", decimal_to_str(cap)),
            CalculationOperand("fact.trade.prior_fund_payment", decimal_to_str(prior_fund_payment)),
        ),
        unrounded_result=decimal_to_str(cap - prior_fund_payment),
        rounding_rule="not_applicable（减法运算，无取整）",
        result=decimal_to_str(upper)))
    calcs.append(CalculationRecord(
        calculation_id="calc.big_pay.capped", formula_id="resident_big_pay_clamp_v1", formula_version="v1",
        operands=(
            CalculationOperand("calc.deductible.copay_base", decimal_to_str(copay_base)),
            CalculationOperand(f"rule.{base_rule_id}", decimal_to_str(base_rate)),
            CalculationOperand("fact.trade.prior_fund_payment", decimal_to_str(prior_fund_payment)),
            CalculationOperand(f"rule.{cap_sel.param.rule_id}", decimal_to_str(cap)),
            CalculationOperand("calc.big_pay.cap_room", decimal_to_str(upper)),
        ),
        unrounded_result=decimal_to_str(raw_unrounded),
        rounding_rule=f"explicit:{rounding_mode.value}(ROP-RND-001 待确认)",
        result=decimal_to_str(pay)))

    big_self_pay = copay_base - pay
    calcs.append(CalculationRecord(
        calculation_id="calc.big_pay.self_pay", formula_id="big_self_pay_v1", formula_version="v1",
        operands=(
            CalculationOperand("calc.deductible.copay_base", decimal_to_str(copay_base)),
            CalculationOperand("calc.big_pay.capped", decimal_to_str(pay)),
        ),
        unrounded_result=decimal_to_str(big_self_pay),
        rounding_rule="not_applicable（减法运算，无取整）",
        result=decimal_to_str(big_self_pay)))
    branches.append(BranchTrace(
        step_id="big_pay.settle", module_id=MODULE_ID, scope_ref="trade",
        condition=BranchCondition("big_pay_settle",
                                  "大额支付=clamp(B×比例, −基金已付, 封顶−基金已付)", "formula",
                                  decimal_to_str(pay), None),
        outcome=BranchOutcome.TRUE,
        rule_refs=(base_rule_id, cap_sel.param.rule_id, "ROP-REF-001"),
        calculation_refs=tuple(c.calculation_id for c in calcs)))
    if raw > upper and copay_base > 0:
        uncertainties.append(DecompositionUncertainty(
            id="u.big_pay.beyond_cap_attribution", code="BEYOND_CAP_FIELD_ATTRIBUTION_UNCONFIRMED",
            message="存在封顶以上费用；其个人承担归属字段（T_BigSelfPay/T_BeyondBig）未确认，未自动归入大额自付。",
            affected_fields=("T_BigSelfPay",)))
    return ResidentBigPayResult(pay, big_self_pay, tuple(branches), tuple(calcs), tuple(uncertainties))
