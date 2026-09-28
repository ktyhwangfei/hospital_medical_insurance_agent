"""门诊大额起付线分解（设计 §7.3）。

定义 ``E`` 为本次确认口径下的合格费用基数，``A`` 为同年度交易前同口径累计，``D`` 为适用起付标准：

    本次起付承担 F = min(E, max(D - A, 0))
    进入后续支付段 B = E - F

硬约束：
- ``A`` 是否交易前累计不明（prior_in_scope_fee_is_pre_trade=False）时保留 unknown 轨迹，不硬算；
- ``T_FirstPay`` 仅为核对目标，不用于反推 D 或覆盖计算的 F（由 reconciliation 层保证）；
- 起付标准版本按结算日期经参数选择函数门控。
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
    PersonKind,
    decimal_to_str,
)
from src.runtime.policy_qa.fee_decomposition.params_employee_outpatient import (
    select_deductible_param,
)

MODULE_ID = "deductible"


@dataclass(frozen=True)
class DeductibleResult:
    """起付线分解结果。F/B 为 None 表示未独立计算（unknown/blocked）。"""

    deductible_paid: Decimal | None  # F：本次起付承担
    copay_base: Decimal | None  # B：进入支付段金额
    branches: tuple[BranchTrace, ...] = ()
    calculations: tuple[CalculationRecord, ...] = ()
    uncertainties: tuple[DecompositionUncertainty, ...] = ()


def decompose_deductible(
    eligible_in_scope: Decimal | None,
    prior_accumulation: Decimal | None,
    prior_is_pre_trade_confirmed: bool,
    person_kind: PersonKind,
    settlement_date: date,
) -> DeductibleResult:
    """起付线分解纯函数。"""
    branches: list[BranchTrace] = []
    calcs: list[CalculationRecord] = []
    uncertainties: list[DecompositionUncertainty] = []

    # 上游基数缺失 → blocked（与规则不适用区分）
    if eligible_in_scope is None:
        branches.append(BranchTrace(
            step_id="deductible.base_available", module_id=MODULE_ID,
            scope_ref="trade",
            condition=BranchCondition("eligible_base", "合格费用基数可用性", "not_null", None, "E"),
            outcome=BranchOutcome.BLOCKED, reason_code="UPSTREAM_BASE_MISSING",
            input_refs=("calc.catalog.total_in_scope",),
        ))
        uncertainties.append(DecompositionUncertainty(
            id="u.deductible.base", code="UPSTREAM_BASE_MISSING",
            message="目录分解未得出完整医保内基数，起付线分解阻断。",
            affected_fields=("T_FirstPay",)))
        return DeductibleResult(None, None, tuple(branches), (), tuple(uncertainties))
    branches.append(BranchTrace(
        step_id="deductible.base_available", module_id=MODULE_ID, scope_ref="trade",
        condition=BranchCondition("eligible_base", "合格费用基数可用性", "not_null",
                                  decimal_to_str(eligible_in_scope), "E"),
        outcome=BranchOutcome.TRUE, input_refs=("calc.catalog.total_in_scope",)))

    # 起付标准参数选择（按身份 + 结算日期）
    sel = select_deductible_param(person_kind, settlement_date)
    branches.append(BranchTrace(
        step_id="deductible.param_select", module_id=MODULE_ID, scope_ref="trade",
        condition=BranchCondition("deductible_param", "起付标准版本选择", "select",
                                  f"{person_kind.value}@{settlement_date.isoformat()}", "EOP-DED-001..004"),
        outcome=sel.outcome, reason_code=sel.reason_code,
        rule_refs=("EOP-DED-001", "EOP-DED-002", "EOP-DED-003", "EOP-DED-004"),
    ))
    if sel.outcome != BranchOutcome.TRUE or sel.param is None or sel.param.value is None:
        uncertainties.append(DecompositionUncertainty(
            id="u.deductible.param", code=sel.reason_code or "PARAM_VERSION_NOT_FOUND",
            message="适用起付标准不能确定，不采用默认值。",
            affected_fields=("T_FirstPay",)))
        return DeductibleResult(None, None, tuple(branches), (), tuple(uncertainties))
    standard = sel.param.value

    # 交易前累计口径确认：不明时保留轨迹不硬算
    if prior_accumulation is None or not prior_is_pre_trade_confirmed:
        branches.append(BranchTrace(
            step_id="deductible.prior_accumulation", module_id=MODULE_ID, scope_ref="trade",
            condition=BranchCondition("prior_accumulation", "交易前同口径年度累计可用且口径已确认",
                                      "confirmed",
                                      decimal_to_str(prior_accumulation) if prior_accumulation is not None else None,
                                      "TB_FeeIn 交易前口径"),
            outcome=BranchOutcome.UNKNOWN,
            reason_code="PRIOR_ACCUMULATION_MISSING" if prior_accumulation is None
            else "PRIOR_ACCUMULATION_CALIBER_UNCONFIRMED",
            input_refs=("fact.trade.prior_in_scope_fee",),
        ))
        uncertainties.append(DecompositionUncertainty(
            id="u.deductible.prior", code=branches[-1].reason_code or "PRIOR_ACCUMULATION_MISSING",
            message="交易前年度累计缺失或口径（交易前/后、是否跨院）未确认，起付金额不能独立计算。",
            affected_fields=("T_FirstPay",)))
        return DeductibleResult(None, None, tuple(branches), (), tuple(uncertainties))
    branches.append(BranchTrace(
        step_id="deductible.prior_accumulation", module_id=MODULE_ID, scope_ref="trade",
        condition=BranchCondition("prior_accumulation", "交易前同口径年度累计可用且口径已确认",
                                  "confirmed", decimal_to_str(prior_accumulation), "TB_FeeIn 交易前口径"),
        outcome=BranchOutcome.TRUE, input_refs=("fact.trade.prior_in_scope_fee",)))

    # F = min(E, max(D - A, 0))；B = E - F（起付不承担取整：输入均为账面精度金额）
    paid = min(eligible_in_scope, max(standard - prior_accumulation, Decimal("0")))
    copay_base = eligible_in_scope - paid
    calc = CalculationRecord(
        calculation_id="calc.deductible.split", formula_id="deductible_split_v1",
        formula_version="v1",
        operands=(
            CalculationOperand("calc.catalog.total_in_scope", decimal_to_str(eligible_in_scope)),
            CalculationOperand("fact.trade.prior_in_scope_fee", decimal_to_str(prior_accumulation)),
            CalculationOperand(f"rule.{sel.param.rule_id}", decimal_to_str(standard)),
        ),
        unrounded_result=decimal_to_str(paid),
        rounding_rule="not_applicable（min/max 运算，无取整）",
        result=decimal_to_str(paid),
    )
    calcs.append(calc)
    branches.append(BranchTrace(
        step_id="deductible.split", module_id=MODULE_ID, scope_ref="trade",
        condition=BranchCondition("deductible_split", "本次起付承担 F=min(E,max(D-A,0))",
                                  "formula", decimal_to_str(paid),
                                  f"E={decimal_to_str(eligible_in_scope)},A={decimal_to_str(prior_accumulation)},D={decimal_to_str(standard)}"),
        outcome=BranchOutcome.TRUE,
        rule_refs=(sel.param.rule_id,),
        input_refs=("calc.catalog.total_in_scope", "fact.trade.prior_in_scope_fee"),
        calculation_refs=(calc.calculation_id,),
    ))
    return DeductibleResult(paid, copay_base, tuple(branches), tuple(calcs), tuple(uncertainties))
