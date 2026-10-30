"""基本医保及补助 → 二次大病保险 → 医疗救助的共用确定性算法。"""
from dataclasses import dataclass
from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    BranchCondition, BranchOutcome, BranchTrace, CalculationOperand, CalculationRecord,
    CheckType, DecompositionCitation, DecompositionUncertainty, FieldReconciliation,
    OutpatientSpecialSnapshot, apply_rounding, decimal_to_str,
)
from src.runtime.policy_qa.fee_decomposition.params_secondary_coverage import (
    AID_SOURCE, ASSISTED_RATE_INCREMENT, BIG_ILL_DEDUCTIBLE, BIG_ILL_FIRST_BAND,
    BIG_ILL_RATES, DB_SOURCE, EFFECTIVE_DATE, SPECIAL_AID_POLICIES,
)
from src.runtime.policy_qa.fee_decomposition.reconciliation import reconcile_field

ZERO = Decimal("0")
_LABELS = {
    "BIG_ILL_PAY": "大病保险支付（二次保障）",
    "FEEIN_DB_PAY": "医保内个人自付一的大病支付",
    "FEEOUT_DB_PAY": "按比例先行自付的大病支付",
    "CIVIL_IN": "医疗救助支付",
    "FEEIN_MAF_PAY": "医保内剩余个人负担的救助",
    "FEEOUT_MAF_PAY": "按比例先行自付剩余负担的救助",
    "PERSON_PAYABLE": "个人应付（对照现金与账户合计）",
}


@dataclass(frozen=True)
class SecondaryCoverageResult:
    big_ill_pay: Decimal | None
    civil_in: Decimal | None
    personal_payable: Decimal | None
    fields: tuple[FieldReconciliation, ...]
    branches: tuple[BranchTrace, ...]
    calculations: tuple[CalculationRecord, ...]
    uncertainties: tuple[DecompositionUncertainty, ...]
    citations: tuple[DecompositionCitation, ...]


def decompose_secondary_coverage(
    snapshot: OutpatientSpecialSnapshot,
    *,
    self_pay_1: Decimal | None,
    proportional_self_pay_2: Decimal | None,
    total_out_scope: Decimal | None,
) -> SecondaryCoverageResult:
    """合规个人负担独立计算；分桶取整仅差一分时按用户确认采用本笔原单。"""
    ctx, obs = snapshot.secondary_coverage, snapshot.observed
    rounding = snapshot.rounding_mode
    branches: list[BranchTrace] = []
    calculations: list[CalculationRecord] = []
    uncertainties: list[DecompositionUncertainty] = []
    amounts: dict[str, Decimal | None] = {code: None for code in _LABELS}

    def unknown(code: str, message: str, affected: tuple[str, ...]) -> None:
        uncertainties.append(DecompositionUncertainty(
            id=f"u.secondary.{code.lower()}", code=code, message=message, affected_fields=affected))
        branches.append(BranchTrace(
            step_id=f"secondary.{code.lower()}", module_id="secondary_coverage", scope_ref="settlement",
            outcome=BranchOutcome.UNKNOWN, reason_code=code))

    def audit(name: str, raw: Decimal, result: Decimal, operands, *, rounded=True, settlement_code: str | None = None) -> None:
        if settlement_code:
            operands = (*operands, (f"fact.secondary.book.{settlement_code.lower()}", result))
        calculations.append(CalculationRecord(
            calculation_id=f"calc.secondary.{name}", formula_id=f"secondary_{name}_v1", formula_version="2023-01-01",
            operands=tuple(CalculationOperand(ref, decimal_to_str(value)) for ref, value in operands),
            unrounded_result=decimal_to_str(raw),
            rounding_rule="settlement_record" if settlement_code else f"explicit:{rounding.value}" if rounded else "not_applicable（精确运算）",
            result=decimal_to_str(result)))

    def record(code: str, raw: Decimal, result: Decimal, *operands: tuple[str, Decimal], settlement_value: bool = False) -> None:
        amounts[code] = result
        audit(code.lower(), raw, result, operands, settlement_code=code if settlement_value else None)
        branches.append(BranchTrace(
            step_id=f"secondary.{code.lower()}", module_id="secondary_coverage", scope_ref="settlement",
            outcome=BranchOutcome.TRUE,
            condition=BranchCondition(code.lower(), _LABELS[code], "formula", decimal_to_str(result)),
            calculation_refs=(f"calc.secondary.{code.lower()}",),
            rule_refs=("SC-DB-001" if "DB" in code or code == "BIG_ILL_PAY" else "SC-MAF-001",)))

    civil_type = snapshot.person.civil_type
    identity_known = civil_type == "0" or civil_type in SPECIAL_AID_POLICIES
    effective = snapshot.settle_date >= EFFECTIVE_DATE
    base_known = all(value is not None and value.is_finite() and value >= 0
                     for value in (self_pay_1, proportional_self_pay_2))
    out_known = total_out_scope is not None and total_out_scope.is_finite() and total_out_scope >= 0
    def whole_cents(value: Decimal | None) -> bool:
        return value is not None and value * 100 == (value * 100).to_integral_value()

    def settlement_amount(code: str, calculated: Decimal, limit: Decimal) -> Decimal:
        """用户确认：分桶取整相差一分时采用原单；缺值、越界或更大差异不回填。"""
        book = getattr(obs, code.lower())
        if (book is not None and book.is_finite() and whole_cents(book)
                and 0 <= book <= limit and abs(book - calculated) == Decimal("0.01")):
            return book
        return calculated

    if base_known and not all(whole_cents(value) for value in (self_pay_1, proportional_self_pay_2)):
        base_known = False
        unknown("SECONDARY_AMOUNT_PRECISION_UNCONFIRMED", "合规个人负担含不足一分钱的金额，源系统精度归并规则未确认，不逐桶取整制造负支付。", tuple(_LABELS))
    if out_known and not whole_cents(total_out_scope):
        out_known = False
        unknown("PERSONAL_AMOUNT_PRECISION_UNCONFIRMED", "医保外金额含不足一分钱的部分，个人应付精度口径未确认。", ("PERSON_PAYABLE",))
    if base_known and out_known and proportional_self_pay_2 is not None and total_out_scope is not None and proportional_self_pay_2 > total_out_scope:
        base_known = False
    if obs.retire_officer_pay is None or obs.retire_officer_pay != 0:
        base_known = False
        unknown("OTHER_SUPPLEMENT_RULE_UNCONFIRMED", "另有补助渠道非零或金额未知，其规则尚未接入，净个人基数不能确认；不直接扣账面目标凑平。", tuple(_LABELS))
    if not effective:
        unknown("SECONDARY_POLICY_NOT_EFFECTIVE", "本次补充的大病及救助规则自2023年起生效，未套用于更早结算。", tuple(_LABELS))
    elif not identity_known:
        unknown("CIVIL_TYPE_UNCONFIRMED", "救助身份缺失或码值未确认，不默认非救助或套用增强待遇。", tuple(_LABELS))
    else:
        assert civil_type is not None  # 身份守卫已排除缺失值。
        if not base_known:
            unknown("SECONDARY_BASE_MISSING", "基本医保、补助或按比例先行负担尚不能确定，二次保障不取账面目标反算。", tuple(_LABELS))
        else:
            assert self_pay_1 is not None and proportional_self_pay_2 is not None
            one, two = self_pay_1, proportional_self_pay_2
            base = one + two
            audit("current_base", base, base, (("calc.secondary.self_pay_1", one), ("calc.secondary.proportional_self_pay_2", two)), rounded=False)
            audit("self_pay_1", one, one, (("input.secondary.self_pay_1_after_supplements", one),), rounded=False)
            audit("proportional_self_pay_2", two, two, (("input.secondary.proportional_self_pay_2", two),), rounded=False)
            assisted = civil_type != "0"
            deductible = BIG_ILL_DEDUCTIBLE / (2 if assisted else 1)
            rates = tuple(rate + (ASSISTED_RATE_INCREMENT if assisted else ZERO) for rate in BIG_ILL_RATES)
            audit("db_deductible", deductible, deductible, (("rule.SC-DB-001.base_deductible", BIG_ILL_DEDUCTIBLE),
                ("rule.SC-DB-002.divisor", Decimal("2") if assisted else Decimal("1"))), rounded=False)
            for rate_name, base_rate, applied_rate in zip(("db_first_rate", "db_second_rate"), BIG_ILL_RATES, rates):
                audit(rate_name, applied_rate, applied_rate, ((f"rule.SC-DB-001.{rate_name}", base_rate),
                    ("rule.SC-DB-002.increment", ASSISTED_RATE_INCREMENT if assisted else ZERO)), rounded=False)
            prior = None
            if ctx.evidence_status == "confirmed" and ctx.is_post_trade is not None and ctx.big_ill_scope_total is not None:
                prior = ctx.big_ill_scope_total - base if ctx.is_post_trade else ctx.big_ill_scope_total
            if base == 0:
                raw_one = raw_two = ZERO
            elif prior is None or not prior.is_finite() or prior < 0:
                raw_one = raw_two = None
                unknown("BIG_ILL_CUMULATIVE_UNCONFIRMED", "交易前年度大病合规个人负担累计缺失、时点未确认或与本笔矛盾，不能确定跨起付/分段位置。", ("BIG_ILL_PAY", "FEEIN_DB_PAY", "FEEOUT_DB_PAY", "CIVIL_IN", "PERSON_PAYABLE"))
            else:
                # 起付以上的前五万元是一段；第二段边界为起付线+50000。
                # 交易后派生仅用于定位分段，属实现口径，不作为用户可见的待核实事项。
                end = prior + base
                first = max(ZERO, min(end, deductible + BIG_ILL_FIRST_BAND) - max(prior, deductible))
                second = max(ZERO, end - max(prior, deductible + BIG_ILL_FIRST_BAND))
                for band_name, band_value in (("first_band_base", first), ("second_band_base", second)):
                    audit(band_name, band_value, band_value, (("calc.secondary.annual_prior", prior),
                        ("calc.secondary.current_base", base), ("rule.SC-DB-001.deductible", deductible),
                        ("rule.SC-DB-001.band_width", BIG_ILL_FIRST_BAND)), rounded=False)
                raw_pay = first * rates[0] + second * rates[1]
                assert ctx.big_ill_scope_total is not None and ctx.is_post_trade is not None
                audit("annual_prior", prior, prior, (
                    ("fact.secondary.big_ill_scope_total", ctx.big_ill_scope_total),
                    ("input.secondary.current_compliant_base", base),
                    ("fact.secondary.is_post_trade", Decimal(int(ctx.is_post_trade)))), rounded=False)
                audit("db_band_total", raw_pay, raw_pay, (
                    ("calc.secondary.annual_prior", prior), ("input.secondary.current_compliant_base", base),
                    ("rule.SC-DB-001.deductible", deductible), ("rule.SC-DB-001.band_width", BIG_ILL_FIRST_BAND),
                    ("input.secondary.first_band_overlap", first), ("rule.SC-DB-001.first_rate", rates[0]),
                    ("input.secondary.second_band_overlap", second), ("rule.SC-DB-001.second_rate", rates[1])), rounded=False)
                # 用户公式中的b为本笔各年度分段的加权比例，两个费用桶使用同一b。
                raw_one = raw_pay * one / base
                raw_two = raw_pay * two / base
                branches.append(BranchTrace(
                    step_id="secondary.db_bands", module_id="secondary_coverage", scope_ref="settlement",
                    outcome=BranchOutcome.TRUE,
                    condition=BranchCondition("annual_bands", "年度大病分段重叠：起付以上五万元及其以上部分", "overlap", decimal_to_str(prior), decimal_to_str(end)),
                    input_refs=("fact.secondary.big_ill_scope_total",), rule_refs=("SC-DB-001", "SC-DB-002")))
            if raw_one is not None:
                assert raw_two is not None
                rounded_one, rounded_two = apply_rounding(raw_one, rounding), apply_rounding(raw_two, rounding)
                db_one = settlement_amount("FEEIN_DB_PAY", rounded_one, one) if raw_one > 0 else rounded_one
                db_two = settlement_amount("FEEOUT_DB_PAY", rounded_two, two) if raw_two > 0 else rounded_two
                record("FEEIN_DB_PAY", raw_one, db_one, ("calc.secondary.self_pay_1", one), ("input.secondary.current_compliant_base", base), ("calc.secondary.db_band_total" if base else "input.secondary.zero_base", raw_one + raw_two), settlement_value=db_one != rounded_one)
                record("FEEOUT_DB_PAY", raw_two, db_two, ("calc.secondary.proportional_self_pay_2", two), ("input.secondary.current_compliant_base", base), ("calc.secondary.db_band_total" if base else "input.secondary.zero_base", raw_one + raw_two), settlement_value=db_two != rounded_two)
                record("BIG_ILL_PAY", raw_one + raw_two, db_one + db_two,
                       ("calc.secondary.feein_db_pay", db_one), ("calc.secondary.feeout_db_pay", db_two))

        # 非救助身份独立得到零救助，无需年度累计或上游费用完整。
        if civil_type == "0":
            for code in ("FEEIN_MAF_PAY", "FEEOUT_MAF_PAY", "CIVIL_IN"):
                record(code, ZERO, ZERO)
        elif amounts["BIG_ILL_PAY"] is not None:
            assert self_pay_1 is not None and proportional_self_pay_2 is not None
            assert amounts["FEEIN_DB_PAY"] is not None and amounts["FEEOUT_DB_PAY"] is not None
            remaining_one = self_pay_1 - amounts["FEEIN_DB_PAY"]
            remaining_two = proportional_self_pay_2 - amounts["FEEOUT_DB_PAY"]
            rate, cap = SPECIAL_AID_POLICIES[civil_type]
            raw_one, raw_two = remaining_one * rate, remaining_two * rate
            pay_one, pay_two = apply_rounding(raw_one, rounding), apply_rounding(raw_two, rounding)
            room = None
            remaining_base = remaining_one + remaining_two
            audit("after_db_one", remaining_one, remaining_one, (("calc.secondary.self_pay_1", self_pay_1), ("calc.secondary.feein_db_pay", amounts["FEEIN_DB_PAY"])), rounded=False)
            audit("after_db_two", remaining_two, remaining_two, (("calc.secondary.proportional_self_pay_2", proportional_self_pay_2), ("calc.secondary.feeout_db_pay", amounts["FEEOUT_DB_PAY"])), rounded=False)
            audit("remaining_base", remaining_base, remaining_base, (("calc.secondary.after_db_one", remaining_one), ("calc.secondary.after_db_two", remaining_two)), rounded=False)
            if cap is not None and remaining_base != 0:
                total = ctx.civil_fund_payment_total
                prior_civil = total if ctx.evidence_status == "confirmed" and ctx.is_post_trade is False else None
                if total is not None and total.is_finite() and total >= 0 and not whole_cents(total):
                    unknown("CIVIL_AMOUNT_PRECISION_UNCONFIRMED", "年度救助支付累计含不足一分钱的金额，剩余封顶额度精度未确认。", ("CIVIL_IN", "FEEIN_MAF_PAY", "FEEOUT_MAF_PAY", "PERSON_PAYABLE"))
                    pay_one = pay_two = None
                elif prior_civil is not None and prior_civil.is_finite() and prior_civil >= 0:
                    room = max(cap - prior_civil, ZERO)
                elif (ctx.evidence_status == "confirmed" and ctx.is_post_trade is True
                      and total is not None and total.is_finite() and total >= 0
                      and pay_one + pay_two <= max(cap - total, ZERO)):
                    # 单向上界证明不跨封顶；不以本笔核对目标反算交易前累计。
                    room = max(cap - total, ZERO)
                else:
                    code = "CIVIL_CAP_PRIOR_UNVERIFIABLE" if ctx.is_post_trade is True else "CIVIL_CUMULATIVE_UNCONFIRMED"
                    unknown(code, "无法用独立交易前救助累计确定剩余额度；交易后累计仅在上界足以证明未跨封顶时可用，不反算本笔救助目标。", ("CIVIL_IN", "FEEIN_MAF_PAY", "FEEOUT_MAF_PAY", "PERSON_PAYABLE"))
                    pay_one = pay_two = None
                if room is not None:
                    assert pay_one is not None and pay_two is not None and total is not None and ctx.is_post_trade is not None
                    audit("civil_cap_room", room, room, (("rule.SC-MAF-001.cap", cap), ("fact.secondary.civil_fund_payment_total", total), ("fact.secondary.is_post_trade", Decimal(int(ctx.is_post_trade)))), rounded=False)
                    if pay_one + pay_two > room:
                        pay_one = apply_rounding(room * remaining_one / remaining_base, rounding)
                        pay_two = room - pay_one
            if pay_one is not None:
                assert pay_two is not None
                calculated_one, calculated_two = pay_one, pay_two
                adopted_one = settlement_amount("FEEIN_MAF_PAY", pay_one, remaining_one) if raw_one > 0 else pay_one
                adopted_two = settlement_amount("FEEOUT_MAF_PAY", pay_two, remaining_two) if raw_two > 0 else pay_two
                if room is None or adopted_one + adopted_two <= room:
                    pay_one, pay_two = adopted_one, adopted_two
                cap_operands = (("calc.secondary.civil_cap_room", room), ("input.secondary.remaining_base", remaining_base)) if room is not None else ()
                record("FEEIN_MAF_PAY", raw_one, pay_one, ("calc.secondary.after_db_one", remaining_one), ("rule.SC-MAF-001", rate), *cap_operands, settlement_value=pay_one != calculated_one)
                record("FEEOUT_MAF_PAY", raw_two, pay_two, ("calc.secondary.after_db_two", remaining_two), ("rule.SC-MAF-001", rate), *cap_operands, settlement_value=pay_two != calculated_two)
                record("CIVIL_IN", raw_one + raw_two, pay_one + pay_two,
                       ("calc.secondary.feein_maf_pay", pay_one), ("calc.secondary.feeout_maf_pay", pay_two))
        if base_known and out_known and amounts["BIG_ILL_PAY"] is not None and amounts["CIVIL_IN"] is not None:
            assert self_pay_1 is not None and total_out_scope is not None
            payable = self_pay_1 + total_out_scope - amounts["BIG_ILL_PAY"] - amounts["CIVIL_IN"]
            record("PERSON_PAYABLE", payable, payable,
                   ("calc.secondary.self_pay_1", self_pay_1), ("input.secondary.total_out_scope", total_out_scope),
                   ("calc.secondary.big_ill_pay", amounts["BIG_ILL_PAY"]), ("calc.secondary.civil_in", amounts["CIVIL_IN"]))

    channel = obs.xjzf + obs.zhzf if obs.xjzf is not None and obs.zhzf is not None else None
    observed = {code: getattr(obs, code.lower(), None) for code in _LABELS}
    observed["PERSON_PAYABLE"] = channel
    fields = tuple(reconcile_field(code, label, CheckType.INDEPENDENT_RECALCULATION,
        amounts[code], observed[code], BranchOutcome.TRUE if amounts[code] is not None else BranchOutcome.UNKNOWN,
        calculation_refs=(f"calc.secondary.{code.lower()}",) if amounts[code] is not None else (),
        citation_refs=("rule.SC-DB-001", "rule.SC-MAF-001")) for code, label in _LABELS.items())
    citations = (
        DecompositionCitation(id="rule.SC-DB-001", kind="policy_document", ref=DB_SOURCE,
            approval_status="用户补充规则，2023-01-01起"),
        DecompositionCitation(id="rule.SC-DB-002", kind="policy_document", ref=AID_SOURCE,
            approval_status="用户补充规则，救助身份起付减半、各段比例加5个百分点"),
        DecompositionCitation(id="rule.SC-MAF-001", kind="policy_document", ref=AID_SOURCE,
            approval_status="用户补充规则，门特按住院救助档"),
    )
    return SecondaryCoverageResult(amounts["BIG_ILL_PAY"], amounts["CIVIL_IN"], amounts["PERSON_PAYABLE"],
        fields, tuple(branches), tuple(calculations), tuple(uncertainties), citations)
