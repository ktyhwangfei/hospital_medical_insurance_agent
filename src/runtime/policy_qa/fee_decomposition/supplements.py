"""退休补充、军残、公疗补助（设计 §7.5；比例与顺序来源 S9/参数表）。

叠加顺序（EOP-PMED-004）：大额 → 退休补助 → 军残补助 → 公疗补助；
享受公疗的在乡残疾军人跳过军残（not_applicable，
reason RURAL_DISABLED_VETERAN_PUBLIC_MEDICAL_EXCLUSION）。

统一纪律（设计 §7.5）：
- 资格确定不满足 → not_applicable（账面已有非零支付的冲突由核对层诊断）；
- 资格未知 → unknown，不得当作不享受；
- 退休军残依赖退休补助独立计算结果：R 未知不得用零代替（blocked）；
  R 明确不适用时按 0 继续并保留不适用依据；
- 公疗不输出负补助：已有支付超目标时保留冲突诊断、O 记 0。
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
    RoundingMode,
    apply_rounding,
    decimal_to_str,
)
from src.runtime.policy_qa.fee_decomposition.params_employee_outpatient import (
    select_military_param,
    select_public_medical_param,
    select_retire_supplement_param,
)

#: 公疗医保内年度累计门槛（参数表 EOP-PMED 系列计算基数口径）
_PMED_THRESHOLD = Decimal("1300")

RURAL_EXCLUSION_REASON = "RURAL_DISABLED_VETERAN_PUBLIC_MEDICAL_EXCLUSION"


@dataclass(frozen=True)
class SupplementResult:
    """补充待遇单项结果。amount=None 表示未计算（unknown/blocked）。"""

    amount: Decimal | None
    outcome: BranchOutcome
    reason_code: str | None = None
    branches: tuple[BranchTrace, ...] = ()
    calculations: tuple[CalculationRecord, ...] = ()
    uncertainties: tuple[DecompositionUncertainty, ...] = ()


def _result(
    module_id: str,
    step: str,
    amount: Decimal | None,
    outcome: BranchOutcome,
    reason: str | None = None,
    branches: tuple[BranchTrace, ...] = (),
    calcs: tuple[CalculationRecord, ...] = (),
    uncertainties: tuple[DecompositionUncertainty, ...] = (),
) -> SupplementResult:
    return SupplementResult(amount, outcome, reason, branches, calcs, uncertainties)


# ── 退休补充保险补助（§7.5.2，EOP-RSUP-001/002） ─────────────────


def retire_supplement(
    copay_self_pay: Decimal | None,
    person_kind: PersonKind,
    retirement_category: str | None,
    enroll_date: date | None,
    settlement_date: date,
    rounding_mode: RoundingMode,
) -> SupplementResult:
    """退休补充保险：普通 50% / 预提 60%，基数=共付段个人自付 S；资格按结算日期。"""
    mid = "retire_supplement"
    branches: list[BranchTrace] = []

    if person_kind != PersonKind.RETIRED:
        branches.append(BranchTrace(
            step_id="rsup.eligibility", module_id=mid, scope_ref="trade",
            condition=BranchCondition("is_retired", "退休身份", "eq", person_kind.value, "retired"),
            outcome=BranchOutcome.NOT_APPLICABLE, reason_code="NOT_RETIRED",
            input_refs=("fact.person.person_type_code",)))
        return _result(mid, "rsup", Decimal("0"), BranchOutcome.NOT_APPLICABLE,
                       "NOT_RETIRED", tuple(branches))

    # 纳入资格时点：以结算日期判断（起始日纳入）
    if enroll_date is None:
        branches.append(BranchTrace(
            step_id="rsup.enroll_date", module_id=mid, scope_ref="trade",
            condition=BranchCondition("enroll_date", "补充保险纳入起始日期", "not_null", None, "纳入日期"),
            outcome=BranchOutcome.UNKNOWN, reason_code="SUPPLEMENT_ENROLL_DATE_MISSING",
            input_refs=("fact.person.retire_supplement_enroll_date",)))
        return _result(mid, "rsup", None, BranchOutcome.UNKNOWN, "SUPPLEMENT_ENROLL_DATE_MISSING",
                       tuple(branches),
                       uncertainties=(DecompositionUncertainty(
                           id="u.rsup.enroll", code="SUPPLEMENT_ENROLL_DATE_MISSING",
                           message="缺少退休补充保险纳入起始日期，不默认已纳入。",
                           affected_fields=("T_BCPay",)),))
    enrolled = settlement_date >= enroll_date
    branches.append(BranchTrace(
        step_id="rsup.enroll_date", module_id=mid, scope_ref="trade",
        condition=BranchCondition("enroll_date", "结算日期≥纳入起始日期（起始日纳入）", "ge",
                                  settlement_date.isoformat(), enroll_date.isoformat()),
        outcome=BranchOutcome.TRUE if enrolled else BranchOutcome.FALSE,
        input_refs=("fact.trade.trade_date", "fact.person.retire_supplement_enroll_date")))
    if not enrolled:
        return _result(mid, "rsup", Decimal("0"), BranchOutcome.NOT_APPLICABLE,
                       "NOT_YET_ENROLLED", tuple(branches))

    if copay_self_pay is None:
        branches.append(BranchTrace(
            step_id="rsup.base", module_id=mid, scope_ref="trade",
            condition=BranchCondition("copay_self_pay", "共付段个人自付 S 可用性", "not_null", None, "S"),
            outcome=BranchOutcome.BLOCKED, reason_code="UPSTREAM_BASE_MISSING",
            input_refs=("calc.big_pay.self_pay",)))
        return _result(mid, "rsup", None, BranchOutcome.BLOCKED, "UPSTREAM_BASE_MISSING",
                       tuple(branches),
                       uncertainties=(DecompositionUncertainty(
                           id="u.rsup.base", code="UPSTREAM_BASE_MISSING",
                           message="大额共付段个人自付未得出，退休补助阻断。", affected_fields=("T_BCPay",)),))

    # 普通/预提类别未知不默认 50%
    sel = select_retire_supplement_param(retirement_category or "", settlement_date)
    branches.append(BranchTrace(
        step_id="rsup.param_select", module_id=mid, scope_ref="trade",
        condition=BranchCondition("retire_category", "退休类别（普通/预提）", "select",
                                  retirement_category, "EOP-RSUP-001/002"),
        outcome=sel.outcome, reason_code=sel.reason_code,
        rule_refs=("EOP-RSUP-001", "EOP-RSUP-002")))
    if sel.outcome != BranchOutcome.TRUE or sel.param is None or sel.param.ratio is None:
        return _result(mid, "rsup", None, BranchOutcome.UNKNOWN,
                       sel.reason_code or "RETIREMENT_CATEGORY_UNKNOWN", tuple(branches),
                       uncertainties=(DecompositionUncertainty(
                           id="u.rsup.category", code=sel.reason_code or "RETIREMENT_CATEGORY_UNKNOWN",
                           message="退休身份已知但普通/预提类别未知，不默认 50%。",
                           affected_fields=("T_BCPay",)),))

    ratio = sel.param.ratio
    unrounded = copay_self_pay * ratio
    amount = apply_rounding(unrounded, rounding_mode)
    calc = CalculationRecord(
        calculation_id="calc.rsup.amount", formula_id="retire_supplement_v1", formula_version="v1",
        operands=(
            CalculationOperand("calc.big_pay.self_pay", decimal_to_str(copay_self_pay)),
            CalculationOperand(f"rule.{sel.param.rule_id}", decimal_to_str(ratio)),
        ),
        unrounded_result=decimal_to_str(unrounded),
        rounding_rule=f"explicit:{rounding_mode.value}(EOP-RND-001 待确认)",
        result=decimal_to_str(amount))
    branches.append(BranchTrace(
        step_id="rsup.amount", module_id=mid, scope_ref="trade",
        condition=BranchCondition("rsup_amount", "R=S×补助比例", "formula",
                                  decimal_to_str(amount), None),
        outcome=BranchOutcome.TRUE, rule_refs=(sel.param.rule_id,),
        calculation_refs=(calc.calculation_id,)))
    return _result(mid, "rsup", amount, BranchOutcome.TRUE, None, tuple(branches), (calc,))


# ── 残疾军人伤残补助（§7.5.3，EOP-DVET-001..004） ────────────────


def military_supplement(
    copay_self_pay: Decimal | None,
    retire_amount: Decimal | None,
    retire_outcome: BranchOutcome,
    person_kind: PersonKind,
    is_disabled_veteran: bool | None,
    grade: str | None,
    eligible_from: date | None,
    eligible_to: date | None,
    is_rural_disabled_veteran: bool | None,
    public_medical_eligible: bool | None,
    fee_dates: tuple[date, ...],
    rounding_mode: RoundingMode,
    *,
    military_disability_level_code: str | None = None,
) -> SupplementResult:
    """军残补助。资格按费用发生日期；退休军残基数为 S-R；公疗在乡军残跳过。"""
    mid = "military_supplement"
    branches: list[BranchTrace] = []

    # 等级0是原始不享受待遇事实，独立于账面金额及正向资格派生开关。
    if military_disability_level_code == "0":
        conflict = is_disabled_veteran is True
        reason = "MILITARY_ELIGIBILITY_FACT_CONFLICT" if conflict else "NO_MILITARY_DISABILITY_BENEFIT"
        outcome = BranchOutcome.UNKNOWN if conflict else BranchOutcome.NOT_APPLICABLE
        branches.append(BranchTrace(
            step_id="dvet.eligibility", module_id=mid, scope_ref="trade",
            condition=BranchCondition("military_disability_level_code", "伤残待遇等级（0为不享受）", "in", "0", "1-6"),
            outcome=outcome, reason_code=reason,
            input_refs=("fact.person.military_disability_level_code",)))
        return _result(mid, "dvet", None if conflict else Decimal("0"), outcome, reason, tuple(branches),
                       uncertainties=(DecompositionUncertainty(
                           id="u.dvet.source_conflict", code=reason,
                           message="伤残待遇等级为不享受，但军残资格标识为享受，来源冲突。",
                           affected_fields=("T_JCPay",)),) if conflict else ())

    if is_disabled_veteran is False:
        branches.append(BranchTrace(
            step_id="dvet.eligibility", module_id=mid, scope_ref="trade",
            condition=BranchCondition("is_disabled_veteran", "残疾军人身份", "eq", "false", "true"),
            outcome=BranchOutcome.NOT_APPLICABLE, reason_code="NOT_DISABLED_VETERAN",
            input_refs=("fact.person.is_disabled_veteran",)))
        return _result(mid, "dvet", Decimal("0"), BranchOutcome.NOT_APPLICABLE,
                       "NOT_DISABLED_VETERAN", tuple(branches))
    if is_disabled_veteran is None:
        branches.append(BranchTrace(
            step_id="dvet.eligibility", module_id=mid, scope_ref="trade",
            condition=BranchCondition("is_disabled_veteran", "残疾军人身份", "eq", None, "true"),
            outcome=BranchOutcome.UNKNOWN, reason_code="DISABLED_VETERAN_STATUS_UNKNOWN",
            input_refs=("fact.person.is_disabled_veteran",)))
        return _result(mid, "dvet", None, BranchOutcome.UNKNOWN, "DISABLED_VETERAN_STATUS_UNKNOWN",
                       tuple(branches),
                       uncertainties=(DecompositionUncertainty(
                           id="u.dvet.status", code="DISABLED_VETERAN_STATUS_UNKNOWN",
                           message="残疾军人身份未知，不按非零支付或退休身份推断资格。",
                           affected_fields=("T_JCPay",)),))

    # 公疗在乡残疾军人排除优先于军残等级计算；资格未知且会改变路径时不默认执行
    if is_rural_disabled_veteran is True and public_medical_eligible is True:
        branches.append(BranchTrace(
            step_id="dvet.rural_pmed_exclusion", module_id=mid, scope_ref="trade",
            condition=BranchCondition("rural_pmed_exclusion", "享受公疗的在乡残疾军人排除", "and",
                                      "rural=true,pmed=true", "排除"),
            outcome=BranchOutcome.NOT_APPLICABLE, reason_code=RURAL_EXCLUSION_REASON,
            rule_refs=("EOP-PMED-003", "EOP-DVET-003", "EOP-DVET-004")))
        return _result(mid, "dvet", Decimal("0"), BranchOutcome.NOT_APPLICABLE,
                       RURAL_EXCLUSION_REASON, tuple(branches))
    if (is_rural_disabled_veteran is None and public_medical_eligible is not False) or (
        is_rural_disabled_veteran is True and public_medical_eligible is None
    ):
        branches.append(BranchTrace(
            step_id="dvet.rural_pmed_exclusion", module_id=mid, scope_ref="trade",
            condition=BranchCondition("rural_pmed_exclusion", "享受公疗的在乡残疾军人排除", "and",
                                      f"rural={is_rural_disabled_veteran},pmed={public_medical_eligible}", "排除"),
            outcome=BranchOutcome.UNKNOWN, reason_code="RURAL_PMED_STATUS_UNKNOWN"))
        return _result(mid, "dvet", None, BranchOutcome.UNKNOWN, "RURAL_PMED_STATUS_UNKNOWN",
                       tuple(branches),
                       uncertainties=(DecompositionUncertainty(
                           id="u.dvet.rural", code="RURAL_PMED_STATUS_UNKNOWN",
                           message="在乡身份/公疗资格未知且会改变路径，不默认执行军残补助。",
                           affected_fields=("T_JCPay",)),))

    if grade not in ("1-4", "5-6"):
        branches.append(BranchTrace(
            step_id="dvet.grade", module_id=mid, scope_ref="trade",
            condition=BranchCondition("military_grade", "伤残等级", "in", grade, "1-4/5-6"),
            outcome=BranchOutcome.UNKNOWN, reason_code="MILITARY_GRADE_UNKNOWN",
            input_refs=("fact.person.military_disability_grade",)))
        return _result(mid, "dvet", None, BranchOutcome.UNKNOWN, "MILITARY_GRADE_UNKNOWN",
                       tuple(branches),
                       uncertainties=(DecompositionUncertainty(
                           id="u.dvet.grade", code="MILITARY_GRADE_UNKNOWN",
                           message="伤残等级缺失或取值未确认。", affected_fields=("T_JCPay",)),))

    # 资格按费用发生日期：全部明细在资格期内才执行；跨资格日的分配依据未确认 → blocked
    if eligible_from is None and eligible_to is None:
        branches.append(BranchTrace(
            step_id="dvet.eligible_period", module_id=mid, scope_ref="trade",
            condition=BranchCondition("eligible_period", "军残资格有效期", "range_contains", None, "资格期"),
            outcome=BranchOutcome.UNKNOWN, reason_code="MILITARY_ELIGIBILITY_PERIOD_UNKNOWN"))
        return _result(mid, "dvet", None, BranchOutcome.UNKNOWN,
                       "MILITARY_ELIGIBILITY_PERIOD_UNKNOWN", tuple(branches),
                       uncertainties=(DecompositionUncertainty(
                           id="u.dvet.period", code="MILITARY_ELIGIBILITY_PERIOD_UNKNOWN",
                           message="缺少军残资格有效期，不能按费用发生日期判定资格。",
                           affected_fields=("T_JCPay",)),))
    in_period = [
        (eligible_from is None or d >= eligible_from) and (eligible_to is None or d <= eligible_to)
        for d in fee_dates
    ]
    if fee_dates and all(in_period):
        branches.append(BranchTrace(
            step_id="dvet.eligible_period", module_id=mid, scope_ref="trade",
            condition=BranchCondition("eligible_period", "全部明细费用发生日期在资格期内",
                                      "range_contains", "all", "资格期"),
            outcome=BranchOutcome.TRUE,
            input_refs=("fact.items.fee_occurrence_date",)))
    elif fee_dates and not any(in_period):
        branches.append(BranchTrace(
            step_id="dvet.eligible_period", module_id=mid, scope_ref="trade",
            condition=BranchCondition("eligible_period", "全部明细费用发生日期在资格期外",
                                      "range_contains", "none", "资格期"),
            outcome=BranchOutcome.FALSE, reason_code="MILITARY_NOT_ELIGIBLE_AT_FEE_DATE"))
        return _result(mid, "dvet", Decimal("0"), BranchOutcome.NOT_APPLICABLE,
                       "MILITARY_NOT_ELIGIBLE_AT_FEE_DATE", tuple(branches))
    else:
        branches.append(BranchTrace(
            step_id="dvet.eligible_period", module_id=mid, scope_ref="trade",
            condition=BranchCondition("eligible_period", "明细费用发生日期跨资格生效日",
                                      "range_contains", "mixed", "资格期"),
            outcome=BranchOutcome.BLOCKED, reason_code="CROSS_DATE_ALLOCATION_UNCONFIRMED"))
        return _result(mid, "dvet", None, BranchOutcome.BLOCKED,
                       "CROSS_DATE_ALLOCATION_UNCONFIRMED", tuple(branches),
                       uncertainties=(DecompositionUncertainty(
                           id="u.dvet.cross_date", code="CROSS_DATE_ALLOCATION_UNCONFIRMED",
                           message="费用跨军残资格生效日且跨日费用在各段的分配依据未确认，该笔军残金额不可独立核验，不按比例摊分。",
                           affected_fields=("T_JCPay",)),))

    if copay_self_pay is None:
        return _result(mid, "dvet", None, BranchOutcome.BLOCKED, "UPSTREAM_BASE_MISSING",
                       tuple(branches) + (BranchTrace(
                           step_id="dvet.base", module_id=mid, scope_ref="trade",
                           condition=BranchCondition("copay_self_pay", "共付段个人自付 S 可用性",
                                                     "not_null", None, "S"),
                           outcome=BranchOutcome.BLOCKED, reason_code="UPSTREAM_BASE_MISSING"),),
                       uncertainties=(DecompositionUncertainty(
                           id="u.dvet.base", code="UPSTREAM_BASE_MISSING",
                           message="大额共付段个人自付未得出，军残补助阻断。", affected_fields=("T_JCPay",)),))

    # 退休军残基数 S-R：R 未知不得用零代替；R 明确不适用时按 0 继续并保留依据
    if person_kind == PersonKind.RETIRED:
        if retire_outcome == BranchOutcome.TRUE and retire_amount is not None:
            base = copay_self_pay - retire_amount
        elif retire_outcome == BranchOutcome.NOT_APPLICABLE:
            base = copay_self_pay  # R=0，不适用依据保留在退休补助分支轨迹
        else:
            branches.append(BranchTrace(
                step_id="dvet.retire_dependency", module_id=mid, scope_ref="trade",
                condition=BranchCondition("retire_dependency", "退休补助独立计算结果可用",
                                          "not_null", retire_outcome.value, "R"),
                outcome=BranchOutcome.BLOCKED, reason_code="RETIRE_SUPPLEMENT_UNKNOWN",
                input_refs=("calc.rsup.amount",)))
            return _result(mid, "dvet", None, BranchOutcome.BLOCKED, "RETIRE_SUPPLEMENT_UNKNOWN",
                           tuple(branches),
                           uncertainties=(DecompositionUncertainty(
                               id="u.dvet.retire_dependency", code="RETIRE_SUPPLEMENT_UNKNOWN",
                               message="退休军残依赖退休补助独立计算结果；R 未知，不以零代替。",
                               affected_fields=("T_JCPay",)),))
    elif person_kind == PersonKind.EMPLOYED:
        base = copay_self_pay
    else:
        return _result(mid, "dvet", None, BranchOutcome.UNKNOWN, "PERSON_KIND_UNKNOWN",
                       tuple(branches))

    # 参数版本按费用发生日期选择；空明细时用资格起始日兜底（保持确定性，不用当前日期）
    sel = select_military_param(
        person_kind, grade, fee_dates[0] if fee_dates else (eligible_from or date(2006, 10, 1))
    )
    branches.append(BranchTrace(
        step_id="dvet.param_select", module_id=mid, scope_ref="trade",
        condition=BranchCondition("military_param", "军残补助比例档选择", "select",
                                  f"{person_kind.value}/{grade}", "EOP-DVET-001..004"),
        outcome=sel.outcome, reason_code=sel.reason_code,
        rule_refs=("EOP-DVET-001", "EOP-DVET-002", "EOP-DVET-003", "EOP-DVET-004")))
    if sel.outcome != BranchOutcome.TRUE or sel.param is None or sel.param.ratio is None:
        return _result(mid, "dvet", None, BranchOutcome.UNKNOWN,
                       sel.reason_code or "MILITARY_GRADE_UNKNOWN", tuple(branches))

    ratio = sel.param.ratio
    unrounded = base * ratio
    amount = apply_rounding(unrounded, rounding_mode)
    calc = CalculationRecord(
        calculation_id="calc.dvet.amount", formula_id="military_supplement_v1", formula_version="v1",
        operands=(
            CalculationOperand("calc.big_pay.self_pay", decimal_to_str(copay_self_pay)),
            CalculationOperand("calc.rsup.amount",
                               decimal_to_str(retire_amount) if retire_amount is not None else "0"),
            CalculationOperand(f"rule.{sel.param.rule_id}", decimal_to_str(ratio)),
        ),
        unrounded_result=decimal_to_str(unrounded),
        rounding_rule=f"explicit:{rounding_mode.value}(EOP-RND-001 待确认)",
        result=decimal_to_str(amount))
    branches.append(BranchTrace(
        step_id="dvet.amount", module_id=mid, scope_ref="trade",
        condition=BranchCondition("dvet_amount", "J=基数×军残比例（退休基数 S-R）", "formula",
                                  decimal_to_str(amount), None),
        outcome=BranchOutcome.TRUE, rule_refs=(sel.param.rule_id,),
        calculation_refs=(calc.calculation_id,)))
    return _result(mid, "dvet", amount, BranchOutcome.TRUE, None, tuple(branches), (calc,))


# ── 单位补充险（原公疗）补助（§7.5.4，EOP-PMED-001..003） ────────


def public_medical_supplement(
    prior_in_scope: Decimal | None,
    current_in_scope: Decimal | None,
    person_kind: PersonKind,
    is_rural_disabled_veteran: bool | None,
    public_medical_eligible: bool | None,
    public_medical_designated: bool | None,
    prior_fund_on_segment: Decimal | None,
    settlement_date: date,
    rounding_mode: RoundingMode,
    raw_indicator: str | None = None,
    raw_code: str | None = None,
) -> SupplementResult:
    """公疗补助：医保内年度累计超 1300 元部分补足目标比例（退休 95%/在职 90%/在乡 100%）。

    G = max(A_in + E_in - 1300, 0) - max(A_in - 1300, 0)
    O = round(G × q) - prior_fund_G；O 须在 [0, G - prior_fund_G]，
    已有支付超目标时保留冲突诊断、不输出负补助。
    """
    mid = "public_medical"
    branches: list[BranchTrace] = []

    # 通道未选择与患者永久资格不同；只接入明确零码，不将陌生码当作否。
    if raw_code == "0" or raw_indicator == "1":
        conflict = public_medical_eligible is True
        reason = ("PUBLIC_MEDICAL_CHANNEL_CONFLICT" if conflict else
                  "PUBLIC_MEDICAL_CHANNEL_NOT_SELECTED" if raw_code == "0" else
                  "NOT_PUBLIC_MEDICAL")
        outcome = BranchOutcome.UNKNOWN if conflict else BranchOutcome.NOT_APPLICABLE
        channel_not_selected = raw_code == "0"
        ref = "fact.person.public_medical_treatment_code" if channel_not_selected else "fact.person.public_medical_flag"
        branches.append(BranchTrace(
            step_id="pmed.eligibility", module_id=mid, scope_ref="trade",
            condition=BranchCondition(
                "public_medical_treatment_code" if channel_not_selected else "public_medical_flag",
                "本笔单位补充医疗保险（原公疗）待遇类别" if channel_not_selected else "公务员待遇标志（0为享受）",
                "eq", raw_code if channel_not_selected else raw_indicator, "3" if channel_not_selected else "0"),
            outcome=outcome, reason_code=reason, input_refs=(ref,)))
        return _result(mid, "pmed", None if conflict else Decimal("0"), outcome, reason, tuple(branches),
                       uncertainties=(DecompositionUncertainty(
                           id="u.pmed.source_conflict", code=reason,
                           message="原公疗通道未选择或标志为不享受，但显式公疗资格为享受，来源冲突。",
                           affected_fields=("T_OfficalPay",)),) if conflict else ())

    if public_medical_eligible is None:
        branches.append(BranchTrace(
            step_id="pmed.eligibility", module_id=mid, scope_ref="trade",
            condition=BranchCondition("pmed_eligible", "公疗资格", "eq", None, "true"),
            outcome=BranchOutcome.UNKNOWN, reason_code="PMED_ELIGIBILITY_UNKNOWN"))
        message = "公疗资格未知，不默认覆盖剩余个人负担。"
        if raw_indicator not in (None, "") or raw_code not in (None, ""):
            met = raw_indicator == "0" and raw_code == "3"
            message = (f"本单原单公疗标识为 {raw_indicator or '空'}、公疗类别码为 {raw_code or '空'}；"
                       f"按待签核口径（标识=0 且类别码=3 才享受）判定为{'已满足' if met else '未满足'}，"
                       "当前仍缺独立资格确认，不能据此判定应支付金额。")
        return _result(mid, "pmed", None, BranchOutcome.UNKNOWN, "PMED_ELIGIBILITY_UNKNOWN",
                       tuple(branches),
                       uncertainties=(DecompositionUncertainty(
                           id="u.pmed.eligibility", code="PMED_ELIGIBILITY_UNKNOWN",
                           message=message,
                           affected_fields=("T_OfficalPay",)),))
    if public_medical_eligible is False:
        branches.append(BranchTrace(
            step_id="pmed.eligibility", module_id=mid, scope_ref="trade",
            condition=BranchCondition("pmed_eligible", "公疗资格", "eq", "false", "true"),
            outcome=BranchOutcome.NOT_APPLICABLE, reason_code="NOT_PUBLIC_MEDICAL"))
        return _result(mid, "pmed", Decimal("0"), BranchOutcome.NOT_APPLICABLE,
                       "NOT_PUBLIC_MEDICAL", tuple(branches))

    if public_medical_designated is None:
        branches.append(BranchTrace(
            step_id="pmed.designated", module_id=mid, scope_ref="trade",
            condition=BranchCondition("designated_hospital", "本人定点医疗机构关系", "eq", None, "true"),
            outcome=BranchOutcome.UNKNOWN, reason_code="DESIGNATED_HOSPITAL_UNKNOWN"))
        return _result(mid, "pmed", None, BranchOutcome.UNKNOWN, "DESIGNATED_HOSPITAL_UNKNOWN",
                       tuple(branches),
                       uncertainties=(DecompositionUncertainty(
                           id="u.pmed.designated", code="DESIGNATED_HOSPITAL_UNKNOWN",
                           message="本人定点关系未知；本人定点与医保定点机构含义不同，需对应人员的有效定点关系。",
                           affected_fields=("T_OfficalPay",)),))
    if public_medical_designated is False:
        branches.append(BranchTrace(
            step_id="pmed.designated", module_id=mid, scope_ref="trade",
            condition=BranchCondition("designated_hospital", "本人定点医疗机构关系", "eq", "false", "true"),
            outcome=BranchOutcome.NOT_APPLICABLE, reason_code="NOT_DESIGNATED_HOSPITAL"))
        return _result(mid, "pmed", Decimal("0"), BranchOutcome.NOT_APPLICABLE,
                       "NOT_DESIGNATED_HOSPITAL", tuple(branches))
    branches.append(BranchTrace(
        step_id="pmed.designated", module_id=mid, scope_ref="trade",
        condition=BranchCondition("designated_hospital", "本人定点医疗机构关系", "eq", "true", "true"),
        outcome=BranchOutcome.TRUE))

    branch_key = (
        "rural_disabled_veteran" if is_rural_disabled_veteran is True
        else "retired" if person_kind == PersonKind.RETIRED
        else "employed" if person_kind == PersonKind.EMPLOYED
        else ""
    )
    sel = select_public_medical_param(branch_key, settlement_date)
    branches.append(BranchTrace(
        step_id="pmed.param_select", module_id=mid, scope_ref="trade",
        condition=BranchCondition("pmed_branch", "公疗分支目标比例选择", "select",
                                  branch_key or None, "EOP-PMED-001/002/003"),
        outcome=sel.outcome, reason_code=sel.reason_code,
        rule_refs=("EOP-PMED-001", "EOP-PMED-002", "EOP-PMED-003")))
    if sel.outcome != BranchOutcome.TRUE or sel.param is None or sel.param.ratio is None:
        return _result(mid, "pmed", None, BranchOutcome.UNKNOWN,
                       sel.reason_code or "PUBLIC_MEDICAL_BRANCH_UNKNOWN", tuple(branches))
    target_ratio = sel.param.ratio

    if prior_in_scope is None or current_in_scope is None:
        branches.append(BranchTrace(
            step_id="pmed.accumulation", module_id=mid, scope_ref="trade",
            condition=BranchCondition("in_scope_accumulation", "医保内年度累计（交易前/本次）可用",
                                      "not_null", None, "A_in/E_in"),
            outcome=BranchOutcome.UNKNOWN, reason_code="PMED_ACCUMULATION_MISSING"))
        return _result(mid, "pmed", None, BranchOutcome.UNKNOWN, "PMED_ACCUMULATION_MISSING",
                       tuple(branches),
                       uncertainties=(DecompositionUncertainty(
                           id="u.pmed.accumulation", code="PMED_ACCUMULATION_MISSING",
                           message="缺少医保内年度累计（交易前或本次），公疗门槛段 G 不能确定。",
                           affected_fields=("T_OfficalPay",)),))

    g = max(prior_in_scope + current_in_scope - _PMED_THRESHOLD, Decimal("0")) - max(
        prior_in_scope - _PMED_THRESHOLD, Decimal("0"))
    branches.append(BranchTrace(
        step_id="pmed.threshold_segment", module_id=mid, scope_ref="trade",
        condition=BranchCondition("pmed_g", "门槛以上本次费用 G=max(A_in+E_in-1300,0)-max(A_in-1300,0)",
                                  "formula", decimal_to_str(g),
                                  f"A_in={decimal_to_str(prior_in_scope)},E_in={decimal_to_str(current_in_scope)}"),
        outcome=BranchOutcome.TRUE if g > 0 else BranchOutcome.FALSE,
        reason_code=None if g > 0 else "BELOW_PMED_THRESHOLD",
        input_refs=("fact.trade.prior_in_scope_fee", "calc.catalog.total_in_scope"),
        rule_refs=(sel.param.rule_id,)))
    if g == 0:
        return _result(mid, "pmed", Decimal("0"), BranchOutcome.TRUE, "BELOW_PMED_THRESHOLD",
                       tuple(branches))

    if prior_fund_on_segment is None:
        branches.append(BranchTrace(
            step_id="pmed.prior_fund", module_id=mid, scope_ref="trade",
            condition=BranchCondition("prior_fund_on_g", "G 段上已有基金支付归属可确定",
                                      "not_null", None, "prior_fund_G"),
            outcome=BranchOutcome.UNKNOWN, reason_code="PMED_PRIOR_FUND_ALLOCATION_UNKNOWN"))
        return _result(mid, "pmed", None, BranchOutcome.UNKNOWN,
                       "PMED_PRIOR_FUND_ALLOCATION_UNKNOWN", tuple(branches),
                       uncertainties=(DecompositionUncertainty(
                           id="u.pmed.prior_fund", code="PMED_PRIOR_FUND_ALLOCATION_UNKNOWN",
                           message="大额/退休/军残支付在 G 段上的归属不能确定，不以整笔基金支付代替适用段支付。",
                           affected_fields=("T_OfficalPay",)),))

    target = apply_rounding(g * target_ratio, rounding_mode)
    raw = target - prior_fund_on_segment
    calc = CalculationRecord(
        calculation_id="calc.pmed.amount", formula_id="public_medical_topup_v1", formula_version="v1",
        operands=(
            CalculationOperand("calc.pmed.g", decimal_to_str(g)),
            CalculationOperand(f"rule.{sel.param.rule_id}", decimal_to_str(target_ratio)),
            CalculationOperand("calc.prior_fund_on_g", decimal_to_str(prior_fund_on_segment)),
        ),
        unrounded_result=decimal_to_str(g * target_ratio),
        rounding_rule=f"explicit:{rounding_mode.value}(EOP-RND-001 待确认)",
        result=decimal_to_str(max(raw, Decimal("0"))))
    if raw < 0:
        # 已有基金支付超过目标：保留冲突与负差额诊断，不输出负补助、不冲减已有基金
        branches.append(BranchTrace(
            step_id="pmed.conflict", module_id=mid, scope_ref="trade",
            condition=BranchCondition("prior_exceeds_target", "已有基金支付≤目标支付", "le",
                                      decimal_to_str(prior_fund_on_segment), decimal_to_str(target)),
            outcome=BranchOutcome.FALSE, reason_code="PMED_PRIOR_EXCEEDS_TARGET",
            calculation_refs=(calc.calculation_id,)))
        return _result(mid, "pmed", Decimal("0"), BranchOutcome.TRUE, "PMED_PRIOR_EXCEEDS_TARGET",
                       tuple(branches), (calc,),
                       uncertainties=(DecompositionUncertainty(
                           id="u.pmed.conflict", code="PMED_PRIOR_EXCEEDS_TARGET",
                           message=(
                               f"G 段已有基金支付 {decimal_to_str(prior_fund_on_segment)} 超过目标 "
                               f"{decimal_to_str(target)}（负差额 {decimal_to_str(raw)}）；"
                               "不输出负补助，是否维持更高待遇需另有确认规则。"),
                           affected_fields=("T_OfficalPay",)),))
    branches.append(BranchTrace(
        step_id="pmed.amount", module_id=mid, scope_ref="trade",
        condition=BranchCondition("pmed_amount", "O=round(G×q)-prior_fund_G（限 [0, G-prior_fund_G]）",
                                  "formula", decimal_to_str(raw), None),
        outcome=BranchOutcome.TRUE, rule_refs=(sel.param.rule_id,),
        calculation_refs=(calc.calculation_id,)))
    return _result(mid, "pmed", raw, BranchOutcome.TRUE, None, tuple(branches), (calc,))
