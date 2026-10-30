"""职工普通门诊费用分解流程编排（设计 §6.1/§7）。

组合选择：仅 ``employee + outpatient``；其他组合明确返回尚不支持，不套用职工门诊公式。
冲正、退款、部分退费或负明细进入明确的未支持重算状态（不取绝对值套正向公式）。

叠加顺序（EOP-PMED-004）：大额 → 退休补助 → 军残补助 → 公疗补助。
公疗 prior_fund_G 归属：仅在快照显式确认医保内费用累计口径一致
（in_scope_basis_aligned=True）且大额/退休/军残金额均已独立得出时，
共付段是 G 段的子集（起付标准 D≥1300），G 段上已有基金支付 = 大额+退休+军残合计
（在乡军残分支不含军残）；否则 prior_fund_G 未知，公疗输出 unknown，
绝不用整笔账面基金支付替代适用段支付。
"""
from __future__ import annotations

from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    BranchCondition,
    BranchOutcome,
    BranchTrace,
    CalculationOperand,
    CalculationRecord,
    CheckStatus,
    CheckType,
    DecompositionCitation,
    DecompositionSnapshot,
    DecompositionUncertainty,
    FieldReconciliation,
    InstitutionKind,
    PersonKind,
    decimal_to_str,
)
from src.runtime.policy_qa.fee_decomposition.big_pay import decompose_big_pay
from src.runtime.policy_qa.fee_decomposition.catalog_split import CatalogRuleLabels, split_catalog
from src.runtime.policy_qa.fee_decomposition.deductible import decompose_deductible
from src.runtime.policy_qa.fee_decomposition.params_employee_outpatient import try_get_param
from src.runtime.policy_qa.fee_decomposition.reconciliation import (
    coverage_counts,
    identity_calculation,
    identity_field,
    overall_reconciliation_status,
    reconcile_field,
)
from src.runtime.policy_qa.fee_decomposition.result import (
    AnswerConstraints,
    CoverageSummary,
    DecompositionProfile,
    SettlementDecompositionResult,
    branch_to_model,
    calc_to_model,
    citation_to_model,
    field_to_model,
    uncertainty_to_model,
)
from src.runtime.policy_qa.fee_decomposition.supplements import (
    military_supplement,
    public_medical_supplement,
    retire_supplement,
)

#: S1 候选人员类别代码（issue_note 来源，正式码表待确认）
EMPLOYED_PERSON_TYPE_CODES = frozenset({"11", "12", "40"})
RETIRED_PERSON_TYPE_CODES = frozenset({
    "21", "22", "25", "26", "41", "42", "54", "56",
    "61", "62", "63", "64", "65", "66", "67", "68",
    "71", "72", "73", "74", "75", "76", "77", "78",
    "81", "82", "83", "84", "85", "86", "87", "88",
    "92", "93", "94", "95", "96", "97", "98", "99",
})

_MODULE_ID = "employee_outpatient"

#: 无待遇原因码候选集（决策记录 D15）：实证 PN_NoRightReason∈{'4','5'} 的 27 笔交易
#: 账面全部 T_FeeIn=0/T_FeeOut=全额（全额自费结算）；码值含义待签核。
_NO_BENEFIT_REASON_CODES = frozenset({"4", "5"})

_FIELD_LABELS = {
    "T_FeeAll": "总费用",
    "T_FeeIn": "医保内费用",
    "T_FeeOut": "医保外费用",
    "T_SelfPay2": "自付二",
    "T_FirstPay": "本次起付承担",
    "T_BigPay": "大额支付",
    "T_BigSelfPay": "大额个人自付",
    "T_BCPay": "退休补充保险补助",
    "T_JCPay": "军残支付",
    "T_OfficalPay": "公疗补充支付",
    "RETIRE_OFFICER_PAY": "退役医疗费支付",
    "T_SelfPay1": "自付一",
    "T_FundPay": "基金合计",
    "T_SelfPayAll": "最终个人承担",
    "T_PersonCountPay": "账户支付",
    "T_CashPay": "现金支付",
}


def classify_person(person_type_code: str | None) -> tuple[PersonKind, BranchTrace]:
    """人员身份分类：S1 候选代码；未知代码不默认在职。"""
    if person_type_code in EMPLOYED_PERSON_TYPE_CODES:
        kind, outcome = PersonKind.EMPLOYED, BranchOutcome.TRUE
    elif person_type_code in RETIRED_PERSON_TYPE_CODES:
        kind, outcome = PersonKind.RETIRED, BranchOutcome.TRUE
    else:
        kind, outcome = PersonKind.UNKNOWN, BranchOutcome.UNKNOWN
    return kind, BranchTrace(
        step_id="person.classify", module_id="person_classification", scope_ref="trade",
        condition=BranchCondition("person_type_code", "人员类别代码属于在职/退休候选集合", "in",
                                  person_type_code, "S1 候选代码集"),
        outcome=outcome, reason_code=None if outcome == BranchOutcome.TRUE else "PERSON_TYPE_UNKNOWN",
        input_refs=("fact.trade.person_type_code",),
        rule_refs=("rule.person_type_codes.issue78",))


def classify_institution(h_level: str | None, h_type: str | None = None) -> tuple[InstitutionKind, BranchTrace]:
    """机构分类：H_TYPE 为主依据（字典 k80：04=社区卫生站/06=村卫生室为社区，
    其余为非社区，决策记录 D9）；H_TYPE 缺失时回落 H_LEVEL 候选（14=社区假设已废弃，
    仅作历史候选保留，实测 14=未评级按未知处理）。"""
    if h_type is not None:
        kind = InstitutionKind.COMMUNITY if h_type in ("04", "06") else InstitutionKind.OTHER
        return kind, BranchTrace(
            step_id="institution.classify", module_id="person_classification", scope_ref="trade",
            condition=BranchCondition("h_type", "机构类型（字典k80：04/06=社区）", "in",
                                      h_type, "04/06"),
            outcome=BranchOutcome.TRUE if kind == InstitutionKind.COMMUNITY else BranchOutcome.FALSE,
            reason_code=None,
            input_refs=("fact.institution.h_type",),
            rule_refs=("rule.h_type_codes.k80",))
    kind = InstitutionKind.UNKNOWN
    outcome = BranchOutcome.UNKNOWN
    reason = "H_TYPE_AND_H_LEVEL_UNKNOWN"
    if h_level is not None:
        try:
            level = int(h_level)
        except ValueError:
            level = -1
        if 0 <= level < 14:
            kind, outcome, reason = InstitutionKind.OTHER, BranchOutcome.FALSE, None
        # level == 14：实测为「未评级」（字典 310），不是社区，按未知处理
    return kind, BranchTrace(
        step_id="institution.classify", module_id="person_classification", scope_ref="trade",
        condition=BranchCondition("h_level", "机构等级（H_TYPE 缺失时回落；14=未评级按未知）", "eq",
                                  h_level, "14"),
        outcome=outcome, reason_code=reason,
        input_refs=("fact.institution.h_level",),
        rule_refs=("rule.h_level_codes.issue78",))


def _empty_result(
    snapshot: DecompositionSnapshot,
    execution_status: str,
    branches: list[BranchTrace],
    uncertainties: list[DecompositionUncertainty],
    citations: list[DecompositionCitation],
) -> SettlementDecompositionResult:
    return SettlementDecompositionResult(
        settlement_ref=snapshot.settlement_ref,
        profile=DecompositionProfile(
            insurance_type=snapshot.insurance_type, medical_category=snapshot.medical_category),
        execution_status=execution_status,
        reconciliation_status="not_verifiable",
        branches=[branch_to_model(b) for b in branches],
        citations=[citation_to_model(c) for c in citations],
        uncertainties=[uncertainty_to_model(u) for u in uncertainties],
        coverage=CoverageSummary(target_field_count=0, independently_explained_count=0,
                                 amount_reconciled_count=0, observed_only_count=0),
        answer_constraints=AnswerConstraints(may_claim_full_explanation=False,
                                             may_infer_missing_rules=False),
    )


def decompose_employee_outpatient(
    snapshot: DecompositionSnapshot,
) -> SettlementDecompositionResult:
    """职工普通门诊费用分解主流程。"""
    branches: list[BranchTrace] = []
    calcs: list[CalculationRecord] = []
    uncertainties: list[DecompositionUncertainty] = []
    citations: list[DecompositionCitation] = [
        DecompositionCitation(
            id="rule.person_type_codes.issue78", kind="issue_note",
            ref="https://github.com/ktyhwangfei/hospital_medical_insurance_agent/issues/78",
            approval_status="pending"),
        DecompositionCitation(
            id="rule.h_level_codes.issue78", kind="issue_note",
            ref="https://github.com/ktyhwangfei/hospital_medical_insurance_agent/issues/78",
            approval_status="pending"),
    ]

    # 1. 组合选择：仅职工+普通门诊
    supported = snapshot.insurance_type == "employee" and snapshot.medical_category == "outpatient"
    branches.append(BranchTrace(
        step_id="flow.profile_select", module_id=_MODULE_ID, scope_ref="trade",
        condition=BranchCondition("profile", "险种×医疗类别组合", "eq",
                                  f"{snapshot.insurance_type}+{snapshot.medical_category}",
                                  "employee+outpatient"),
        outcome=BranchOutcome.TRUE if supported else BranchOutcome.NOT_APPLICABLE,
        reason_code=None if supported else "UNSUPPORTED_PROFILE"))
    if not supported:
        uncertainties.append(DecompositionUncertainty(
            id="u.flow.unsupported_profile", code="UNSUPPORTED_PROFILE",
            message="首期仅支持城镇职工×普通门诊；其他组合尚不支持，不套用职工门诊公式。",
            affected_fields=()))
        return _empty_result(snapshot, "unavailable", branches, uncertainties, citations)

    # 2. 冲正/负明细：进入未支持重算状态
    has_negative = any(it.fee < 0 or (it.count is not None and it.count < 0) for it in snapshot.items)
    is_reversal = snapshot.trade.is_reversal or snapshot.trade.original_trade_no is not None
    branches.append(BranchTrace(
        step_id="flow.reversal_check", module_id=_MODULE_ID, scope_ref="trade",
        condition=BranchCondition("reversal_or_negative", "冲正/退款/负明细", "or",
                                  f"reversal={is_reversal},negative={has_negative}", "正向已结算"),
        outcome=BranchOutcome.FALSE if (is_reversal or has_negative) else BranchOutcome.TRUE,
        reason_code="UNSUPPORTED_REVERSAL_OR_NEGATIVE" if (is_reversal or has_negative) else None,
        rule_refs=("EOP-REF-001", "EOP-REF-002")))
    if is_reversal or has_negative:
        uncertainties.append(DecompositionUncertainty(
            id="u.flow.reversal", code="UNSUPPORTED_REVERSAL_OR_NEGATIVE",
            message="冲正/退款/负明细交易进入未支持重算状态，不取绝对值套正向公式。",
            affected_fields=tuple(_FIELD_LABELS)))
        return _empty_result(snapshot, "unavailable", branches, uncertainties, citations)

    # 2.5 无待遇全额自费分支（决策记录 D15）：原因码命中时按确定性规则分解——
    # 全部费用个人承担，医保内/起付/大额/各项补助均为 0；码值含义未签核，如实留痕
    no_right = snapshot.trade.no_right_reason
    branches.append(BranchTrace(
        step_id="flow.no_benefit_check", module_id=_MODULE_ID, scope_ref="trade",
        condition=BranchCondition("no_right_reason", "无待遇原因码（'4'/'5'=全额自费候选）",
                                  "in", no_right, "4/5"),
        outcome=BranchOutcome.TRUE if no_right in _NO_BENEFIT_REASON_CODES
        else BranchOutcome.FALSE,
        reason_code=None if no_right in _NO_BENEFIT_REASON_CODES else "BENEFIT_SETTLED",
        input_refs=("fact.trade.no_right_reason",),
        rule_refs=("rule.no_right_reason.d15",)))
    if no_right in _NO_BENEFIT_REASON_CODES:
        uncertainties.append(DecompositionUncertainty(
            id="u.flow.no_benefit_semantics", code="NO_BENEFIT_REASON_SEMANTICS_UNCONFIRMED",
            message=(f"PN_NoRightReason='{no_right}' 实证对应全额自费结算（27/27 笔），"
                     "码值含义与适用范围待签核；按无待遇规则分解不升级为已确认口径。"),
            affected_fields=()))
        citations.append(DecompositionCitation(
            id="fact.trade.no_right_reason", kind="settlement_fact",
            ref=f"snapshot:{snapshot.settlement_ref}/trade/PN_NoRightReason",
            value=no_right))
        return _no_benefit_result(snapshot, branches, uncertainties, citations)

    # 3. 身份与机构分类
    person_kind, person_branch = classify_person(snapshot.person.person_type_code)
    branches.append(person_branch)
    institution_kind, inst_branch = classify_institution(
        snapshot.institution.h_level, snapshot.institution.h_type)
    branches.append(inst_branch)
    citations.append(DecompositionCitation(
        id="fact.trade.person_type_code", kind="settlement_fact",
        ref=f"snapshot:{snapshot.settlement_ref}/trade/PN_PersonType",
        value=snapshot.person.person_type_code))
    for ref, column, value in (
        ("fact.person.military_disability_level_code", "P_JCLevel", snapshot.person.military_disability_level_code),
        ("fact.person.public_medical_flag", "P_Official", snapshot.person.public_medical_flag),
        ("fact.person.public_medical_treatment_code", "P_OfficialCode", snapshot.person.public_medical_treatment_code),
    ):
        if value is not None:
            citations.append(DecompositionCitation(
                id=ref, kind="settlement_fact",
                ref=f"snapshot:{snapshot.settlement_ref}/trade/{column}", value=value))

    # 4. 三大目录逐项分解（按费用发生日期匹配；规则编号按本链 EOP 口径显式传入）
    split = split_catalog(
        snapshot.items, snapshot.drug_catalog, snapshot.service_catalog,
        snapshot.material_catalog, snapshot.trade.hospital_code, snapshot.rounding_mode,
        rules=CatalogRuleLabels(rounding_rule_id="EOP-RND-001", catalog_rule_ref="EOP-CAT 系列"))
    branches.extend(split.branches)
    calcs.extend(split.calculations)
    uncertainties.extend(split.uncertainties)
    if split.fatal_issue is not None:
        return _empty_result(snapshot, "unavailable", branches, uncertainties, citations)

    # 5. 起付线：E 取目录分解完整医保内合计
    deductible = decompose_deductible(
        split.total_in_scope if split.is_complete else None,
        snapshot.accumulation.prior_in_scope_fee,
        snapshot.accumulation.prior_in_scope_fee_is_pre_trade,
        person_kind, snapshot.trade.trade_date)
    branches.extend(deductible.branches)
    calcs.extend(deductible.calculations)
    uncertainties.extend(deductible.uncertainties)

    # 6. 大额支付：B = E - F
    big = decompose_big_pay(
        deductible.copay_base, person_kind, snapshot.person.birth_date,
        institution_kind, snapshot.trade.trade_date,
        snapshot.accumulation.prior_fund_payment,
        snapshot.accumulation.prior_fund_payment_is_pre_trade,
        snapshot.rounding_mode)
    branches.extend(big.branches)
    calcs.extend(big.calculations)
    uncertainties.extend(big.uncertainties)

    # 7. 补充待遇链：S → R → J → O
    rsup = retire_supplement(
        big.big_self_pay, person_kind, snapshot.person.retirement_category,
        snapshot.person.retire_supplement_enroll_date, snapshot.trade.trade_date,
        snapshot.rounding_mode)
    branches.extend(rsup.branches)
    calcs.extend(rsup.calculations)
    uncertainties.extend(rsup.uncertainties)

    dvet = military_supplement(
        big.big_self_pay, rsup.amount, rsup.outcome, person_kind,
        snapshot.person.is_disabled_veteran, snapshot.person.military_disability_grade,
        snapshot.person.military_eligible_from, snapshot.person.military_eligible_to,
        snapshot.person.is_rural_disabled_veteran, snapshot.person.public_medical_eligible,
        tuple(it.fee_occurrence_date for it in snapshot.items),
        snapshot.rounding_mode,
        military_disability_level_code=snapshot.person.military_disability_level_code)
    branches.extend(dvet.branches)
    calcs.extend(dvet.calculations)
    uncertainties.extend(dvet.uncertainties)

    # 公疗 prior_fund_G：口径确认一致且上游金额均已独立得出时，
    # 共付段 ⊆ G 段（D≥1300），G 段已有基金支付 = 大额+退休+军残（在乡分支不含军残）
    rural_excluded = dvet.reason_code == "RURAL_DISABLED_VETERAN_PUBLIC_MEDICAL_EXCLUSION"
    chain_amounts = [big.big_pay, rsup.amount]
    if not rural_excluded:
        chain_amounts.append(dvet.amount)
    prior_fund_on_g: Decimal | None = None
    if (
        snapshot.accumulation.in_scope_basis_aligned
        and snapshot.accumulation.prior_in_scope_fee_is_pre_trade
        and all(a is not None for a in chain_amounts)
    ):
        prior_fund_on_g = sum(chain_amounts, Decimal("0"))  # type: ignore[arg-type]

    pmed = public_medical_supplement(
        snapshot.accumulation.prior_in_scope_fee
        if snapshot.accumulation.prior_in_scope_fee_is_pre_trade else None,
        split.total_in_scope if split.is_complete else None,
        person_kind, snapshot.person.is_rural_disabled_veteran,
        snapshot.person.public_medical_eligible, snapshot.person.public_medical_designated,
        prior_fund_on_g, snapshot.trade.trade_date, snapshot.rounding_mode,
        raw_indicator=snapshot.person.public_medical_flag,
        raw_code=snapshot.person.public_medical_treatment_code)
    branches.extend(pmed.branches)
    calcs.extend(pmed.calculations)
    uncertainties.extend(pmed.uncertainties)

    # 8. 取整规则待确认的全局不确定性（EOP-RND-001；模式已显式传入并记录于各计算记录）
    uncertainties.append(DecompositionUncertainty(
        id="u.rounding.rule", code="ROUNDING_RULE_PENDING_CONFIRMATION",
        message=f"取整规则 EOP-RND-001 待确认；本次计算显式采用 {snapshot.rounding_mode.value}，结果不升级为已确认口径。",
        affected_fields=()))

    # 8.1 轨迹引用到的参数表规则进入 citations（带来源确认状态，未确认不升级）
    cited_rules = sorted({
        ref for b in branches for ref in b.rule_refs if ref.startswith("EOP-")
    } | {
        ref.removeprefix("rule.")
        for c in calcs for o in c.operands for ref in (o.ref,) if ref.startswith("rule.EOP-")
    })
    for rule_id in cited_rules:
        param = try_get_param(rule_id)
        if param is not None:
            citations.append(DecompositionCitation(
                id=f"rule.{rule_id}", kind="policy_document", ref=param.source,
                value=rule_id, values=(param.version,), approval_status=param.confirmation_status))
    citations.append(DecompositionCitation(
        id="fact.trade.trade_date", kind="settlement_fact",
        ref=f"snapshot:{snapshot.settlement_ref}/trade/T_TradeDate",
        value=snapshot.trade.trade_date.isoformat()))

    # 9. 逐字段核对（§10）：观测值仅作核对目标
    fields, identity_calcs = _build_fields(snapshot, split, deductible, big, rsup, dvet, pmed)
    calcs.extend(identity_calcs)
    recon_status = overall_reconciliation_status(tuple(fields))

    # 10. 总体执行状态：存在 unknown/blocked 分支或目录不完整 → partial
    has_unknown = any(
        b.outcome in (BranchOutcome.UNKNOWN, BranchOutcome.BLOCKED) for b in branches)
    execution = "complete" if (split.is_complete and not has_unknown) else "partial"

    cov = coverage_counts(tuple(fields))
    return SettlementDecompositionResult(
        settlement_ref=snapshot.settlement_ref,
        profile=DecompositionProfile(
            insurance_type=snapshot.insurance_type, medical_category=snapshot.medical_category),
        execution_status=execution,
        fee_items=list(split.explanations),
        reconciliation_status=recon_status,
        fields=[field_to_model(f) for f in fields],
        branches=[branch_to_model(b) for b in branches],
        calculations=[calc_to_model(c) for c in calcs],
        citations=[citation_to_model(c) for c in citations],
        uncertainties=[uncertainty_to_model(u) for u in uncertainties],
        coverage=CoverageSummary(**cov),
        answer_constraints=AnswerConstraints(
            may_claim_full_explanation=(execution == "complete" and recon_status == "matched"),
            may_infer_missing_rules=False),
    )


def _identity_entry(
    field_code: str,
    label: str,
    observed: Decimal | None,
    operands: tuple[tuple[str, Decimal | None], ...],
    *,
    calculation_id: str,
    formula_id: str,
) -> tuple[FieldReconciliation, CalculationRecord | None]:
    """账面恒等字段 + 轨迹记录：分量齐全时附 CalculationRecord（解释投影 1.1）。

    只记录本来已执行的恒等加减，不改变核对语义；分量缺失时不产生记录，
    字段回落"未记录本步计算"的保守解释。
    """
    components = tuple(value for _, value in operands)
    if observed is None or any(v is None for v in components):
        return identity_field(field_code, label, observed, components), None
    calc = identity_calculation(
        calculation_id, formula_id,
        tuple(
            CalculationOperand(ref, decimal_to_str(value))
            for ref, value in operands
            if value is not None
        ))
    return (
        identity_field(field_code, label, observed, components,
                       calculation_refs=(calc.calculation_id,)),
        calc,
    )


def _no_benefit_result(
    snapshot: DecompositionSnapshot,
    branches: list[BranchTrace],
    uncertainties: list[DecompositionUncertainty],
    citations: list[DecompositionCitation],
) -> SettlementDecompositionResult:
    """无待遇全额自费交易的确定性分解：全部费用个人承担，医保内与各支付段为 0。"""
    obs = snapshot.observed
    sum_fee = sum((it.fee for it in snapshot.items), Decimal("0"))
    zero = Decimal("0")
    identity_calcs: list[CalculationRecord] = []

    def _identity(field_code, label, observed, operands, *, calculation_id, formula_id):
        entry, calc = _identity_entry(
            field_code, label, observed, operands,
            calculation_id=calculation_id, formula_id=formula_id)
        if calc is not None:
            identity_calcs.append(calc)
        return entry

    # 无待遇全额自费：总额与个人支付均由明细逐行合计得出（不依赖目录/待遇计算）
    if sum_fee is not None:
        identity_calcs.append(CalculationRecord(
            calculation_id="calc.catalog.total_fee", formula_id="catalog_total_fee_v1",
            formula_version="v1",
            operands=(CalculationOperand("fact.items.fee", decimal_to_str(sum_fee)),),
            unrounded_result=decimal_to_str(sum_fee),
            rounding_rule="not_applicable（明细逐行合计，无取整）",
            result=decimal_to_str(sum_fee)))
    entries: list[FieldReconciliation] = [
        reconcile_field("T_FeeAll", _FIELD_LABELS["T_FeeAll"], CheckType.DETAIL_AGGREGATION,
                        sum_fee, obs.fee_all, BranchOutcome.TRUE,
                        calculation_refs=("calc.catalog.total_fee",)),
        _identity("T_FeeAll.identity", _FIELD_LABELS["T_FeeAll"] + "（账面恒等 In+Out）",
                  obs.fee_all, (("T_FeeIn", obs.fee_in), ("T_FeeOut", obs.fee_out)),
                  calculation_id="calc.identity.fee_all", formula_id="identity_fee_all_v1"),
        # 无待遇规则：医保内=0、全部费用计入医保外（个人承担），自付二=0
        reconcile_field("T_FeeIn", _FIELD_LABELS["T_FeeIn"], CheckType.INDEPENDENT_RECALCULATION,
                        zero, obs.fee_in, BranchOutcome.TRUE),
        reconcile_field("T_FeeOut", _FIELD_LABELS["T_FeeOut"], CheckType.INDEPENDENT_RECALCULATION,
                        sum_fee, obs.fee_out, BranchOutcome.TRUE),
        reconcile_field("T_SelfPay2", _FIELD_LABELS["T_SelfPay2"], CheckType.INDEPENDENT_RECALCULATION,
                        zero, obs.self_pay_2, BranchOutcome.TRUE),
        reconcile_field("T_FirstPay", _FIELD_LABELS["T_FirstPay"], CheckType.INDEPENDENT_RECALCULATION,
                        zero, obs.first_pay, BranchOutcome.TRUE),
        reconcile_field("T_BigPay", _FIELD_LABELS["T_BigPay"], CheckType.INDEPENDENT_RECALCULATION,
                        zero, obs.big_pay, BranchOutcome.TRUE),
        reconcile_field("T_BigSelfPay", _FIELD_LABELS["T_BigSelfPay"],
                        CheckType.INDEPENDENT_RECALCULATION,
                        zero, obs.big_self_pay, BranchOutcome.TRUE),
        reconcile_field("T_BCPay", _FIELD_LABELS["T_BCPay"], CheckType.INDEPENDENT_RECALCULATION,
                        zero, obs.bc_pay, BranchOutcome.TRUE),
        reconcile_field("T_JCPay", _FIELD_LABELS["T_JCPay"], CheckType.INDEPENDENT_RECALCULATION,
                        zero, obs.jc_pay, BranchOutcome.TRUE),
        reconcile_field("T_OfficalPay", _FIELD_LABELS["T_OfficalPay"],
                        CheckType.INDEPENDENT_RECALCULATION,
                        zero, obs.official_pay, BranchOutcome.TRUE),
        reconcile_field("RETIRE_OFFICER_PAY", _FIELD_LABELS["RETIRE_OFFICER_PAY"],
                        CheckType.INDEPENDENT_RECALCULATION, None, obs.retire_officer_pay,
                        BranchOutcome.UNKNOWN, "SETTLEMENT_FACT_ONLY"),
        _identity("T_SelfPay1", _FIELD_LABELS["T_SelfPay1"], obs.self_pay_1,
                  (("T_FeeIn", obs.fee_in),
                   ("T_BigPay", obs.big_pay.copy_negate() if obs.big_pay is not None else None),
                   ("T_OfficalPay", obs.official_pay.copy_negate() if obs.official_pay is not None else None)),
                  calculation_id="calc.identity.self_pay_1",
                  formula_id="identity_self_pay_1_v1"),
        _no_benefit_self_pay_all(sum_fee, obs, identity_calcs),
        _identity("T_SelfPayAll.vs_fee_all_minus_fund",
                  _FIELD_LABELS["T_SelfPayAll"] + "（对照 FeeAll-FundPay）",
                  obs.self_pay_all,
                  (("T_FeeAll", obs.fee_all),
                   ("T_FundPay", obs.fund_pay.copy_negate() if obs.fund_pay is not None else None)),
                  calculation_id="calc.identity.self_pay_all_vs_fund",
                  formula_id="identity_self_pay_all_vs_fund_v1"),
    ]
    for code in ("T_PersonCountPay", "T_CashPay"):
        value = obs.person_count_pay if code == "T_PersonCountPay" else obs.cash_pay
        entries.append(reconcile_field(
            code, _FIELD_LABELS[code], CheckType.DETAIL_AGGREGATION,
            None, value, BranchOutcome.UNKNOWN, "PAYMENT_CHANNEL_REPLAY_UNAVAILABLE"))
    recon_status = overall_reconciliation_status(tuple(entries))
    cov = coverage_counts(tuple(entries))
    return SettlementDecompositionResult(
        settlement_ref=snapshot.settlement_ref,
        profile=DecompositionProfile(
            insurance_type=snapshot.insurance_type, medical_category=snapshot.medical_category),
        execution_status="complete",
        reconciliation_status=recon_status,
        fields=[field_to_model(f) for f in entries],
        branches=[branch_to_model(b) for b in branches],
        calculations=[calc_to_model(c) for c in identity_calcs],
        citations=[citation_to_model(c) for c in citations],
        uncertainties=[uncertainty_to_model(u) for u in uncertainties],
        coverage=CoverageSummary(**cov),
        answer_constraints=AnswerConstraints(
            may_claim_full_explanation=(recon_status == "matched"),
            may_infer_missing_rules=False),
    )


def _no_benefit_self_pay_all(sum_fee: Decimal | None, obs, calcs: list[CalculationRecord]) -> FieldReconciliation:
    """无待遇全额自费：个人支付 = 明细逐行费用合计，不依赖待遇计算。"""
    if sum_fee is not None:
        calcs.append(CalculationRecord(
            calculation_id="calc.self_pay_all.parts", formula_id="self_pay_all_components_v1",
            formula_version="v1",
            operands=(CalculationOperand("calc.catalog.total_fee", decimal_to_str(sum_fee)),),
            unrounded_result=decimal_to_str(sum_fee),
            rounding_rule="not_applicable（明细逐行合计，无取整）",
            result=decimal_to_str(sum_fee)))
        return reconcile_field(
            "T_SelfPayAll", _FIELD_LABELS["T_SelfPayAll"], CheckType.INDEPENDENT_RECALCULATION,
            sum_fee, obs.self_pay_all, BranchOutcome.TRUE,
            calculation_refs=("calc.self_pay_all.parts",))
    return identity_field(
        "T_SelfPayAll", _FIELD_LABELS["T_SelfPayAll"], obs.self_pay_all,
        (obs.first_pay, obs.fee_out, obs.big_self_pay,
         obs.bc_pay.copy_negate() if obs.bc_pay is not None else None,
         obs.jc_pay.copy_negate() if obs.jc_pay is not None else None,
         obs.official_pay.copy_negate() if obs.official_pay is not None else None,
         obs.retire_officer_pay.copy_negate() if obs.retire_officer_pay is not None else None),
        calculation_refs=("calc.identity.self_pay_all",))


def _build_fields(
    snapshot: DecompositionSnapshot,
    split,
    deductible,
    big,
    rsup,
    dvet,
    pmed,
) -> tuple[list[FieldReconciliation], list[CalculationRecord]]:
    """按设计 §10 核对矩阵生成全部目标字段结果项（含零值与缺失值）。

    返回 (字段结果, 恒等式轨迹记录)；轨迹只记录本来已执行的加减，不改核对语义。
    """
    obs = snapshot.observed
    sum_fee = split.total_fee if split.fatal_issue is None else None
    sum_book_in = sum((it.fee_in for it in snapshot.items if it.fee_in is not None), Decimal("0"))
    book_in_complete = all(it.fee_in is not None for it in snapshot.items)
    sum_book_out = sum((it.fee_out for it in snapshot.items if it.fee_out is not None), Decimal("0"))
    book_out_complete = all(it.fee_out is not None for it in snapshot.items)
    sum_book_sp2 = sum((it.self_pay_2 for it in snapshot.items if it.self_pay_2 is not None), Decimal("0"))
    book_sp2_complete = all(it.self_pay_2 is not None for it in snapshot.items)

    identity_calcs: list[CalculationRecord] = []

    def _identity(field_code, label, observed, operands, *, calculation_id, formula_id):
        entry, calc = _identity_entry(
            field_code, label, observed, operands,
            calculation_id=calculation_id, formula_id=formula_id)
        if calc is not None:
            identity_calcs.append(calc)
        return entry

    entries: list[FieldReconciliation] = [
        # 总费用：明细账面 ΣFee 汇总核对；另列账面恒等 T_FeeIn+T_FeeOut 对照
        reconcile_field("T_FeeAll", _FIELD_LABELS["T_FeeAll"], CheckType.DETAIL_AGGREGATION,
                        sum_fee, obs.fee_all,
                        BranchOutcome.TRUE if sum_fee is not None else BranchOutcome.BLOCKED,
                        calculation_refs=("calc.catalog.total_fee",)),
        _identity("T_FeeAll.identity", _FIELD_LABELS["T_FeeAll"] + "（账面恒等 In+Out）",
                  obs.fee_all, (("T_FeeIn", obs.fee_in), ("T_FeeOut", obs.fee_out)),
                  calculation_id="calc.identity.fee_all", formula_id="identity_fee_all_v1"),
        # 医保内：独立目录分解 vs 交易账面；另列明细账面汇总三层差异
        reconcile_field("T_FeeIn", _FIELD_LABELS["T_FeeIn"], CheckType.INDEPENDENT_RECALCULATION,
                        split.total_in_scope, obs.fee_in,
                        BranchOutcome.TRUE if split.is_complete else BranchOutcome.UNKNOWN,
                        calculation_refs=("calc.catalog.total_in_scope",)),
        reconcile_field("T_FeeIn.detail", _FIELD_LABELS["T_FeeIn"] + "（明细账面汇总）",
                        CheckType.DETAIL_AGGREGATION,
                        sum_book_in if book_in_complete else None, obs.fee_in,
                        BranchOutcome.TRUE if book_in_complete else BranchOutcome.UNKNOWN),
        reconcile_field("T_FeeOut", _FIELD_LABELS["T_FeeOut"], CheckType.INDEPENDENT_RECALCULATION,
                        split.total_out_scope, obs.fee_out,
                        BranchOutcome.TRUE if split.is_complete else BranchOutcome.UNKNOWN,
                        calculation_refs=("calc.catalog.total_out_scope",)),
        reconcile_field("T_FeeOut.detail", _FIELD_LABELS["T_FeeOut"] + "（明细账面汇总）",
                        CheckType.DETAIL_AGGREGATION,
                        sum_book_out if book_out_complete else None, obs.fee_out,
                        BranchOutcome.TRUE if book_out_complete else BranchOutcome.UNKNOWN),
        # 自付二：独立逐行计算 vs 交易账面；明细账面汇总另列（不自付二重复计入个人负担）
        reconcile_field("T_SelfPay2", _FIELD_LABELS["T_SelfPay2"], CheckType.INDEPENDENT_RECALCULATION,
                        split.total_self_pay_2, obs.self_pay_2,
                        BranchOutcome.TRUE if split.is_complete else BranchOutcome.UNKNOWN,
                        calculation_refs=("calc.catalog.total_self_pay_2",)),
        reconcile_field("T_SelfPay2.detail", _FIELD_LABELS["T_SelfPay2"] + "（明细账面汇总）",
                        CheckType.DETAIL_AGGREGATION,
                        sum_book_sp2 if book_sp2_complete else None, obs.self_pay_2,
                        BranchOutcome.TRUE if book_sp2_complete else BranchOutcome.UNKNOWN),
        # 起付/大额
        reconcile_field("T_FirstPay", _FIELD_LABELS["T_FirstPay"], CheckType.INDEPENDENT_RECALCULATION,
                        deductible.deductible_paid, obs.first_pay,
                        BranchOutcome.TRUE if deductible.deductible_paid is not None else (
                            deductible.branches[-1].outcome if deductible.branches else BranchOutcome.UNKNOWN),
                        calculation_refs=tuple(c.calculation_id for c in deductible.calculations)),
        reconcile_field("T_BigPay", _FIELD_LABELS["T_BigPay"], CheckType.INDEPENDENT_RECALCULATION,
                        big.big_pay, obs.big_pay,
                        BranchOutcome.TRUE if big.big_pay is not None else BranchOutcome.UNKNOWN,
                        calculation_refs=tuple(c.calculation_id for c in big.calculations)),
        reconcile_field("T_BigSelfPay", _FIELD_LABELS["T_BigSelfPay"],
                        CheckType.INDEPENDENT_RECALCULATION,
                        big.big_self_pay, obs.big_self_pay,
                        BranchOutcome.TRUE if big.big_self_pay is not None else BranchOutcome.UNKNOWN,
                        calculation_refs=("calc.big_pay.self_pay",)),
        # 补充待遇
        reconcile_field("T_BCPay", _FIELD_LABELS["T_BCPay"], CheckType.INDEPENDENT_RECALCULATION,
                        rsup.amount, obs.bc_pay, rsup.outcome, rsup.reason_code,
                        calculation_refs=tuple(c.calculation_id for c in rsup.calculations)),
        reconcile_field("T_JCPay", _FIELD_LABELS["T_JCPay"], CheckType.INDEPENDENT_RECALCULATION,
                        dvet.amount, obs.jc_pay, dvet.outcome, dvet.reason_code,
                        calculation_refs=tuple(c.calculation_id for c in dvet.calculations),
                        citation_refs=tuple(ref for branch in dvet.branches for ref in branch.input_refs
                                            if ref == "fact.person.military_disability_level_code")),
        reconcile_field("T_OfficalPay", _FIELD_LABELS["T_OfficalPay"],
                        CheckType.INDEPENDENT_RECALCULATION,
                        pmed.amount, obs.official_pay, pmed.outcome, pmed.reason_code,
                        calculation_refs=tuple(c.calculation_id for c in pmed.calculations),
                        citation_refs=tuple(ref for branch in pmed.branches for ref in branch.input_refs
                                            if ref in ("fact.person.public_medical_flag", "fact.person.public_medical_treatment_code"))),
        reconcile_field("RETIRE_OFFICER_PAY", _FIELD_LABELS["RETIRE_OFFICER_PAY"],
                        CheckType.INDEPENDENT_RECALCULATION, None, obs.retire_officer_pay,
                        BranchOutcome.UNKNOWN, "SETTLEMENT_FACT_ONLY"),
    ]

    # 自付一：能按本单独立计算的起付承担＋大额个人自付分解时走重算；
    # 分量缺失才退回账面恒等式（只用观测分量，不证明字段原因）。
    # 注意：账面自付一还会扣减公疗/军残/退休补助等渠道（如 2026 样本：医保内-大额-公疗），
    # 分量式只含起付+大额自付，遇到非零补助渠道必须退回恒等式，否则会与账面差出补助金额。
    subsidy_channels_absent = all(
        value is None or value == 0
        for value in (obs.official_pay, obs.jc_pay, obs.bc_pay))
    if (deductible.deductible_paid is not None and big.big_self_pay is not None
            and subsidy_channels_absent):
        self_pay_1_parts = deductible.deductible_paid + big.big_self_pay
        identity_calcs.append(CalculationRecord(
            calculation_id="calc.self_pay_1.parts",
            formula_id="self_pay_1_components_v1",
            formula_version="v1",
            operands=(
                CalculationOperand("calc.deductible.split", decimal_to_str(deductible.deductible_paid)),
                CalculationOperand("calc.big_pay.self_pay", decimal_to_str(big.big_self_pay)),
            ),
            unrounded_result=decimal_to_str(self_pay_1_parts),
            rounding_rule="not_applicable（加法，无取整）",
            result=decimal_to_str(self_pay_1_parts)))
        entries.append(reconcile_field(
            "T_SelfPay1", _FIELD_LABELS["T_SelfPay1"], CheckType.INDEPENDENT_RECALCULATION,
            self_pay_1_parts, obs.self_pay_1, BranchOutcome.TRUE,
            calculation_refs=("calc.self_pay_1.parts",)))
    else:
        entries.append(_identity(
            "T_SelfPay1", _FIELD_LABELS["T_SelfPay1"], obs.self_pay_1,
            (("T_FeeIn", obs.fee_in),
             ("T_BigPay", obs.big_pay.copy_negate() if obs.big_pay is not None else None),
             ("T_OfficalPay", obs.official_pay.copy_negate() if obs.official_pay is not None else None)),
            calculation_id="calc.identity.self_pay_1", formula_id="identity_self_pay_1_v1"))
    # 基金合计候选公式：本单另有非零基金渠道则不适用；渠道是否穷尽未知则不可核对
    if snapshot.has_other_fund_channels is True:
        entries.append(FieldReconciliation(
            field_code="T_FundPay", label=_FIELD_LABELS["T_FundPay"],
            check_type=CheckType.IDENTITY_CHECK,
            check_status=CheckStatus.NOT_APPLICABLE,
            observed_amount=decimal_to_str(obs.fund_pay) if obs.fund_pay is not None else None,
            reason_code="FUND_CHANNELS_NOT_EXHAUSTED"))
    elif snapshot.has_other_fund_channels is None:
        # 渠道穷尽性未知时仍可给出"已列示渠道重算"：退役医疗费为 0 且各渠道均有独立计算。
        channel_amounts = (big.big_pay, rsup.amount, dvet.amount, pmed.amount)
        fund_ready = obs.retire_officer_pay == 0 and all(amount is not None for amount in channel_amounts)
        fund_channels = [(cid, amount) for cid, amount in (
            ("calc.big_pay.segmented", big.big_pay),
            *((records[-1].calculation_id, amount) for records, amount in (
                (rsup.calculations, rsup.amount), (dvet.calculations, dvet.amount),
                (pmed.calculations, pmed.amount)) if amount is not None and amount != 0 and records),
        ) if amount is not None and amount != 0] if fund_ready else []
        if fund_ready:
            fund_total = sum((amount for _, amount in fund_channels), Decimal("0"))
            identity_calcs.append(CalculationRecord(
                calculation_id="calc.fund.total.parts", formula_id="fund_total_components_v1",
                formula_version="v1",
                operands=tuple(CalculationOperand(cid, decimal_to_str(amount)) for cid, amount in fund_channels),
                unrounded_result=decimal_to_str(fund_total), rounding_rule="not_applicable（加法，无取整）",
                result=decimal_to_str(fund_total)))
            entries.append(reconcile_field(
                "T_FundPay", _FIELD_LABELS["T_FundPay"], CheckType.INDEPENDENT_RECALCULATION,
                fund_total, obs.fund_pay, BranchOutcome.TRUE,
                calculation_refs=("calc.fund.total.parts",)))
        else:
            entries.append(FieldReconciliation(
                field_code="T_FundPay", label=_FIELD_LABELS["T_FundPay"],
                check_type=CheckType.IDENTITY_CHECK,
                check_status=CheckStatus.NOT_VERIFIABLE,
                observed_amount=decimal_to_str(obs.fund_pay) if obs.fund_pay is not None else None,
                reason_code="FUND_CHANNELS_EXHAUSTIVENESS_UNKNOWN"))
    else:
        entries.append(_identity(
            "T_FundPay", _FIELD_LABELS["T_FundPay"], obs.fund_pay,
            (("T_BigPay", obs.big_pay), ("T_BCPay", obs.bc_pay),
             ("T_JCPay", obs.jc_pay), ("T_OfficalPay", obs.official_pay),
             ("RETIRE_OFFICER_PAY", obs.retire_officer_pay)),
            calculation_id="calc.identity.fund_pay", formula_id="identity_fund_pay_v1"))
    # 仅核对已读取的支付事实，不据此宣称基金渠道已穷尽或退役待遇已独立重算。
    entries.append(_identity(
        "T_FundPay.listed_channels", "基金合计（已列示渠道账面构成）", obs.fund_pay,
        (("T_BigPay", obs.big_pay), ("T_BCPay", obs.bc_pay),
         ("T_JCPay", obs.jc_pay), ("T_OfficalPay", obs.official_pay),
         ("RETIRE_OFFICER_PAY", obs.retire_officer_pay),
         ("T_BigillPay", obs.bigill_pay), ("NT_CivilPay", obs.civil_pay)),
        calculation_id="calc.identity.fund_pay.listed_channels", formula_id="identity_listed_fund_pay_v1"))
    personal_parts = [
        ("calc.deductible.split", deductible.deductible_paid, 1),
        ("calc.catalog.total_out_scope", split.total_out_scope, 1),
        ("calc.big_pay.self_pay", big.big_self_pay, 1),
    ]
    for records, amount in ((rsup.calculations, rsup.amount), (dvet.calculations, dvet.amount),
                            (pmed.calculations, pmed.amount)):
        if amount is not None and records:
            personal_parts.append((records[-1].calculation_id, amount, -1))
    # 退役医疗费仅账面列示且无独立计算：非零或未取得时不得声称已独立重算。
    personal_ready = (all(value is not None for _, value, _ in personal_parts)
                      and obs.retire_officer_pay is not None and obs.retire_officer_pay == 0)
    if personal_ready:
        personal_total = sum((value * sign for _, value, sign in personal_parts if value is not None), Decimal("0"))
        identity_calcs.append(CalculationRecord(
            calculation_id="calc.self_pay_all.parts",
            formula_id="self_pay_all_components_v1",
            formula_version="v1",
            operands=tuple(CalculationOperand(cid, decimal_to_str(value * sign))
                           for cid, value, sign in personal_parts),
            unrounded_result=decimal_to_str(personal_total),
            rounding_rule="not_applicable（加减，无取整）",
            result=decimal_to_str(personal_total)))
        entries.append(reconcile_field(
            "T_SelfPayAll", _FIELD_LABELS["T_SelfPayAll"], CheckType.INDEPENDENT_RECALCULATION,
            personal_total, obs.self_pay_all, BranchOutcome.TRUE,
            calculation_refs=("calc.self_pay_all.parts",)))
    else:
        entries.append(_identity(
            "T_SelfPayAll", _FIELD_LABELS["T_SelfPayAll"], obs.self_pay_all,
            (("T_FirstPay", obs.first_pay), ("T_FeeOut", obs.fee_out),
             ("T_BigSelfPay", obs.big_self_pay),
             ("T_BCPay", obs.bc_pay.copy_negate() if obs.bc_pay is not None else None),
             ("T_JCPay", obs.jc_pay.copy_negate() if obs.jc_pay is not None else None),
             ("T_OfficalPay", obs.official_pay.copy_negate() if obs.official_pay is not None else None),
             ("RETIRE_OFFICER_PAY", obs.retire_officer_pay.copy_negate() if obs.retire_officer_pay is not None else None)),
            calculation_id="calc.identity.self_pay_all", formula_id="identity_self_pay_all_v1"))
    # 与 FeeAll-FundPay 独立核对（账面恒等，不证明字段原因）
    entries.append(_identity(
        "T_SelfPayAll.vs_fee_all_minus_fund",
        _FIELD_LABELS["T_SelfPayAll"] + "（对照 FeeAll-FundPay）",
        obs.self_pay_all,
        (("T_FeeAll", obs.fee_all),
         ("T_FundPay", obs.fund_pay.copy_negate() if obs.fund_pay is not None else None)),
        calculation_id="calc.identity.self_pay_all_vs_fund",
        formula_id="identity_self_pay_all_vs_fund_v1"))
    # 渠道恒等（对照居民链）：账户支付+现金支付 = 最终个人承担
    entries.append(_identity(
        "T_SelfPayAll.channel", _FIELD_LABELS["T_SelfPayAll"] + "（渠道恒等 账户+现金）",
        obs.self_pay_all,
        (("T_PersonCountPay", obs.person_count_pay), ("T_CashPay", obs.cash_pay)),
        calculation_id="calc.identity.self_pay_all_channel",
        formula_id="identity_self_pay_channel_v1"))
    # 账户/现金：缺少当时扣款规则与支付流水，仅报告账面渠道金额
    for code in ("T_PersonCountPay", "T_CashPay"):
        value = obs.person_count_pay if code == "T_PersonCountPay" else obs.cash_pay
        entries.append(reconcile_field(
            code, _FIELD_LABELS[code], CheckType.DETAIL_AGGREGATION,
            None, value, BranchOutcome.UNKNOWN, "PAYMENT_CHANNEL_REPLAY_UNAVAILABLE"))
    return entries, identity_calcs
