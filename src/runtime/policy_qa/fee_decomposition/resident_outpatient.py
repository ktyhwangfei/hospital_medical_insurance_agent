"""城乡居民普通门诊费用分解流程编排（Issue #80，设计 §1 居民×门诊组合）。

与职工门诊（employee_outpatient）的关系：
- 复用：三大目录逐项分解（split_catalog，ROP-CAT-000 居民目录划分与职工基本相同）、
  逐字段核对（reconciliation）、结果契约（result）与公开视图（public_view）；
- 差异：起付/支付比例按**机构等级档**分档（100/550 元、55%/50%，2018-01-01 起），
  无在职/退休身份维度，无退休/军残/公疗补充待遇链（对应字段恒 not_applicable）；
- 扩展：支持**退费交易**分解（区间重叠公式统一正负交易，ROP-REF-001/002；
  职工内核拦截为 unavailable）；
- 通道分流（T_CureType）：11/19 → 门诊大额待遇通道（起付+比例+封顶）；
  17/18 → 医事服务费通道（限额内 100% 基金支付、不累计门急诊待遇，ROP-MSF-001）；
  17/18/19 为院内扩展码（字典 300 未覆盖），语义待确认，全部结果附候选口径声明。

无待遇分支（ROP-NRB-001）：PN_NoRightReason 非空即全额自费（居民口径，实证 25/25 笔），
正负交易统一（退费的全自费交易 FeeOut=负值镜像）。
"""
from __future__ import annotations
from dataclasses import replace

from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    BranchCondition,
    BranchOutcome,
    BranchTrace,
    CalculationOperand,
    CalculationRecord,
    CheckType,
    DecompositionCitation,
    DecompositionSnapshot,
    DecompositionUncertainty,
    FieldReconciliation,
    InstitutionLevelTier,
    decimal_to_str,
)
from src.runtime.policy_qa.fee_decomposition.catalog_split import CatalogRuleLabels, split_catalog
from src.runtime.policy_qa.fee_decomposition.params_resident_outpatient import (
    MSF_CURE_TYPE_CODES,
    OUTPATIENT_CURE_TYPE_CODES,
    RESIDENT_PERSON_TYPE_CODES,
    try_get_param,
)
from src.runtime.policy_qa.fee_decomposition.reconciliation import (
    coverage_counts,
    identity_calculation,
    identity_field,
    overall_reconciliation_status,
    reconcile_field,
)
from src.runtime.policy_qa.fee_decomposition.resident_big_pay import (
    decompose_resident_big_pay,
)
from src.runtime.policy_qa.fee_decomposition.resident_deductible import (
    decompose_resident_deductible,
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

_MODULE_ID = "resident_outpatient"
ALGORITHM_VERSION = "resident_outpatient_v1"

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
    "T_SelfPay1": "自付一",
    "T_FundPay": "基金合计",
    "T_BigillPay": "大病保险支付",
    "T_SelfPayAll": "最终个人承担",
    "T_PersonCountPay": "账户支付",
    "T_CashPay": "现金支付",
}


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


def _empty_result(
    snapshot: DecompositionSnapshot,
    execution_status: str,
    branches: list[BranchTrace],
    uncertainties: list[DecompositionUncertainty],
    citations: list[DecompositionCitation],
) -> SettlementDecompositionResult:
    return SettlementDecompositionResult(
        algorithm_version=ALGORITHM_VERSION,
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


def decompose_resident_outpatient(
    snapshot: DecompositionSnapshot,
) -> SettlementDecompositionResult:
    """城乡居民普通门诊费用分解主流程。"""
    actual_trade_date = snapshot.trade.trade_date
    branches: list[BranchTrace] = []
    calcs: list[CalculationRecord] = []
    uncertainties: list[DecompositionUncertainty] = []
    citations: list[DecompositionCitation] = [
        DecompositionCitation(
            id="rule.person_type_codes.issue80", kind="issue_note",
            ref="https://github.com/ktyhwangfei/hospital_medical_insurance_agent/issues/80",
            approval_status="pending"),
        DecompositionCitation(
            id="rule.cure_type_extension.issue80", kind="issue_note",
            ref="https://github.com/ktyhwangfei/hospital_medical_insurance_agent/issues/80",
            approval_status="pending"),
    ]

    # 1. 组合选择：仅居民+普通门诊
    supported = snapshot.insurance_type == "resident" and snapshot.medical_category == "outpatient"
    branches.append(BranchTrace(
        step_id="flow.profile_select", module_id=_MODULE_ID, scope_ref="trade",
        condition=BranchCondition("profile", "险种×医疗类别组合", "eq",
                                  f"{snapshot.insurance_type}+{snapshot.medical_category}",
                                  "resident+outpatient"),
        outcome=BranchOutcome.TRUE if supported else BranchOutcome.NOT_APPLICABLE,
        reason_code=None if supported else "UNSUPPORTED_PROFILE"))
    if not supported:
        uncertainties.append(DecompositionUncertainty(
            id="u.flow.unsupported_profile", code="UNSUPPORTED_PROFILE",
            message="本内核仅支持城乡居民×普通门诊；其他组合尚不支持，不套用居民门诊公式。",
            affected_fields=()))
        return _empty_result(snapshot, "unavailable", branches, uncertainties, citations)

    # 退费保留实际交易锚点；参数选择使用已确认原单政策、人员和机构。
    refund = bool(snapshot.trade.original_trade_no) or any(item.fee < 0 for item in snapshot.items)
    if refund:
        original = snapshot.original_policy_context
        valid = (original is not None and original.insurance_type == "resident"
                 and original.medical_category == "outpatient"
                 and original.policy_date <= actual_trade_date
                 and original.accumulation_year == original.policy_date.year
                 and original.person.person_type_code is not None
                 and original.institution.h_level is not None)
        branches.append(BranchTrace(
            step_id="flow.original_policy", module_id=_MODULE_ID, scope_ref="trade",
            outcome=BranchOutcome.TRUE if valid else BranchOutcome.UNKNOWN,
            reason_code=None if valid else "ORIGINAL_POLICY_CONTEXT_UNCONFIRMED",
            input_refs=("fact.original_policy_context",), rule_refs=("ROP-REF-001", "ROP-REF-002")))
        if valid:
            assert original is not None
            snapshot = replace(snapshot, person=original.person, institution=original.institution,
                trade=replace(snapshot.trade, trade_date=original.policy_date,
                              cure_type=original.cure_type, no_right_reason=original.no_right_reason))
            citations.append(DecompositionCitation(
                id="fact.original.policy_date", kind="settlement_fact",
                ref=f"snapshot:{snapshot.settlement_ref}/original_policy_context", value=original.policy_date.isoformat()))
        else:
            snapshot = replace(snapshot, trade=replace(snapshot.trade, no_right_reason=None, cure_type=None),
                accumulation=replace(snapshot.accumulation,
                prior_in_scope_fee_is_pre_trade=False, prior_fund_payment_is_pre_trade=False,
                prior_fund_payment=None))
            uncertainties.append(DecompositionUncertainty(
                id="u.refund.original_policy", code="ORIGINAL_POLICY_CONTEXT_UNCONFIRMED",
                message="退费原单政策、身份、机构或被退年度累计证据缺失，不使用退费当天政策重算。",
                affected_fields=("T_FirstPay", "T_BigPay", "T_BigSelfPay", "T_BigillPay")))

    # 2. 医疗类别扩展码候选口径声明（ROP-CURE-001：17/18/19 字典 300 未覆盖）
    cure_type = snapshot.trade.cure_type
    uncertainties.append(DecompositionUncertainty(
        id="u.flow.cure_type_extension", code="CURE_TYPE_EXTENSION_SEMANTICS_UNCONFIRMED",
        message=(f"T_CureType='{cure_type}'：17/18/19 为院内扩展码（字典 300 未覆盖），"
                 "19 按普通门诊待遇通道、17/18 按医事服务费通道处理属实证候选口径，待签核。"),
        affected_fields=()))

    # 2.5 无待遇全额自费分支（ROP-NRB-001）：PN_NoRightReason 非空即全额自费，
    # 正负交易统一（退费的无待遇交易为负值镜像）；码值含义待签核，如实留痕
    no_right = snapshot.trade.no_right_reason
    branches.append(BranchTrace(
        step_id="flow.no_benefit_check", module_id=_MODULE_ID, scope_ref="trade",
        condition=BranchCondition("no_right_reason", "无待遇原因码（非空=全额自费，居民口径）",
                                  "not_empty", no_right, "空"),
        outcome=BranchOutcome.TRUE if no_right else BranchOutcome.FALSE,
        reason_code=None if no_right else "BENEFIT_SETTLED",
        input_refs=("fact.trade.no_right_reason",),
        rule_refs=("ROP-NRB-001",)))
    if no_right:
        uncertainties.append(DecompositionUncertainty(
            id="u.flow.no_benefit_semantics", code="NO_BENEFIT_REASON_SEMANTICS_UNCONFIRMED",
            message=(f"PN_NoRightReason='{no_right}' 实证对应全额自费结算（25/25 笔），"
                     "码值含义与适用范围待签核；按无待遇规则分解不升级为已确认口径。"),
            affected_fields=()))
        citations.append(DecompositionCitation(
            id="fact.trade.no_right_reason", kind="settlement_fact",
            ref=f"snapshot:{snapshot.settlement_ref}/trade/PN_NoRightReason",
            value=no_right))
        return _no_benefit_result(snapshot, branches, uncertainties, citations)

    # 3. 退费/冲正识别（居民支持退费分解，ROP-REF-001/002；不拦截）：
    # 负明细或关联原交易号 → 退费通道，区间重叠公式按退费时点累计回推
    has_negative = any(it.fee < 0 or (it.count is not None and it.count < 0) for it in snapshot.items)
    is_refund = (
        has_negative
        or snapshot.trade.original_trade_no is not None
        or (snapshot.observed.fee_all is not None and snapshot.observed.fee_all < 0)
    )
    branches.append(BranchTrace(
        step_id="flow.refund_check", module_id=_MODULE_ID, scope_ref="trade",
        condition=BranchCondition("refund_or_negative", "退费/冲正/负明细（居民支持区间公式分解）",
                                  "or", f"refund={is_refund},negative={has_negative}", "正向或退费均可分解"),
        outcome=BranchOutcome.TRUE if is_refund else BranchOutcome.FALSE,
        reason_code=None,
        rule_refs=("ROP-REF-001", "ROP-REF-002")))

    # 4. 人员类别留痕（2018 新政策起付/比例不区分人群；类别仅核对不进入计算）
    person_code = snapshot.person.person_type_code
    person_in_candidates = person_code in RESIDENT_PERSON_TYPE_CODES
    branches.append(BranchTrace(
        step_id="person.classify", module_id="person_classification", scope_ref="trade",
        condition=BranchCondition("person_type_code", "居民人员类别候选集合（字典290）", "in",
                                  person_code, "14-20/50/70/80"),
        outcome=BranchOutcome.TRUE if person_in_candidates else BranchOutcome.UNKNOWN,
        reason_code=None if person_in_candidates else "PERSON_TYPE_OUTSIDE_CANDIDATE",
        input_refs=("fact.trade.person_type_code",),
        rule_refs=("ROP-PERSON-001",)))
    if not person_in_candidates:
        uncertainties.append(DecompositionUncertainty(
            id="u.person.type_outside_candidate", code="PERSON_TYPE_OUTSIDE_CANDIDATE",
            message=(f"PN_PersonType='{person_code}' 不在居民人员类别候选集合（issue80）；"
                     "2018 新政策起付/比例按机构等级分档与身份无关，继续计算。"),
            affected_fields=()))
    citations.append(DecompositionCitation(
        id="fact.trade.person_type_code", kind="settlement_fact",
        ref=f"snapshot:{snapshot.settlement_ref}/trade/PN_PersonType",
        value=person_code))

    # 5. 机构等级档分类（居民起付/比例分档维度：H_LEVEL>=10 一级及以下含未评级）
    tier = _classify_tier(snapshot.institution.h_level, branches)

    # 6. 三大目录逐项分解（复用职工 catalog_split，ROP-CAT-000；按费用发生日期匹配；
    #    规则编号按本链 ROP 口径显式传入，不串用职工 EOP 编号）
    split = split_catalog(
        snapshot.items, snapshot.drug_catalog, snapshot.service_catalog,
        snapshot.material_catalog, snapshot.trade.hospital_code, snapshot.rounding_mode,
        rules=CatalogRuleLabels(rounding_rule_id="ROP-RND-001", catalog_rule_ref="ROP-CAT-000"))
    branches.extend(split.branches)
    calcs.extend(split.calculations)
    uncertainties.extend(split.uncertainties)
    if split.fatal_issue is not None:
        return _empty_result(snapshot, "unavailable", branches, uncertainties, citations)

    # 7. 通道分流：医事服务费通道（17/18）vs 门诊大额通道（11/19）；
    # 门诊大额通道内再判大病保险通道（ROP-BIGILL-001）与救助渠道声明（ROP-CIVIL-001）
    in_msf_channel = cure_type in MSF_CURE_TYPE_CODES
    in_outpatient_channel = cure_type in OUTPATIENT_CURE_TYPE_CODES
    branches.append(BranchTrace(
        step_id="flow.channel_select", module_id=_MODULE_ID, scope_ref="trade",
        condition=BranchCondition("cure_type_channel", "结算通道分流（T_CureType）", "in",
                                  cure_type, "17/18=医事服务费；11/19=门诊大额"),
        outcome=BranchOutcome.TRUE if (in_msf_channel or in_outpatient_channel) else BranchOutcome.UNKNOWN,
        reason_code=None if (in_msf_channel or in_outpatient_channel) else "CURE_TYPE_CHANNEL_UNKNOWN",
        input_refs=("fact.trade.cure_type",),
        rule_refs=("ROP-MSF-001", "ROP-CURE-001")))

    # 救助渠道存在性检测（观测值只用于渠道判定与核对策略调整，不作计算输入）：
    # NT_CivilPay≠0 → 交易级 FeeOut/SelfPay2/SelfPay1/BigSelfPay 口径含救助冲抵，
    # 内核这些字段标 not_verifiable 不判定对错（ROP-CIVIL-001，口径与冲抵顺序未确认）
    civil_pay = snapshot.observed.civil_pay
    civil_pay_present = civil_pay is not None and civil_pay != 0
    branches.append(BranchTrace(
        step_id="flow.civil_pay_check", module_id=_MODULE_ID, scope_ref="trade",
        condition=BranchCondition("civil_pay_present", "民政救助渠道支付存在性（NT_CivilPay≠0）",
                                  "ne", decimal_to_str(civil_pay) if civil_pay is not None else None, "0"),
        outcome=BranchOutcome.TRUE if civil_pay_present else BranchOutcome.FALSE,
        reason_code=None,
        input_refs=("fact.trade.civil_pay",),
        rule_refs=("ROP-CIVIL-001",)))
    if civil_pay_present:
        assert civil_pay is not None
        uncertainties.append(DecompositionUncertainty(
            id="u.flow.civil_pay_channel", code="CIVIL_PAY_CHANNEL_PRESENT",
            message=(f"本单存在民政救助支付（NT_CivilPay={decimal_to_str(civil_pay)}），"
                     "交易级医保外/自付二/自付一/大额自付口径含救助冲抵（冲抵规则未确认），"
                     "这些字段不与门诊大额口径账面值直接比对。"),
            affected_fields=("T_FeeOut", "T_SelfPay2", "T_SelfPay1", "T_BigSelfPay")))

    # 大病保险通道判定（ROP-BIGILL-001 候选口径）：门诊大额交易前累计已达当年封顶
    # 且救助渠道未支付 → 医保内及比例先行负担进入大病渠道，全自费/超限排除。
    in_bigill_channel = False
    bigill_cap_sel = None
    if in_outpatient_channel and not civil_pay_present:
        from src.runtime.policy_qa.fee_decomposition.params_resident_outpatient import (
            select_resident_cap_param,
        )
        bigill_cap_sel = select_resident_cap_param(snapshot.trade.trade_date)
        cap_value = (
            bigill_cap_sel.param.value
            if bigill_cap_sel.outcome == BranchOutcome.TRUE and bigill_cap_sel.param is not None
            else None
        )
        prior_fund = snapshot.accumulation.prior_fund_payment
        if (
            cap_value is not None
            and prior_fund is not None
            and snapshot.accumulation.prior_fund_payment_is_pre_trade
            and prior_fund >= cap_value
        ):
            in_bigill_channel = True
    if in_outpatient_channel and not civil_pay_present:
        branches.append(BranchTrace(
            step_id="flow.bigill_channel_check", module_id=_MODULE_ID, scope_ref="trade",
            condition=BranchCondition(
                "bigill_channel", "门诊大额累计已达封顶→大病保险通道", "ge",
                decimal_to_str(snapshot.accumulation.prior_fund_payment)
                if snapshot.accumulation.prior_fund_payment is not None else None,
                "当年封顶线"),
            outcome=BranchOutcome.TRUE if in_bigill_channel else BranchOutcome.FALSE,
            reason_code=None,
            input_refs=("fact.trade.prior_fund_payment",),
            rule_refs=("ROP-BIGILL-001",)))
    elif in_outpatient_channel and civil_pay_present:
        branches.append(BranchTrace(
            step_id="flow.bigill_channel_check", module_id=_MODULE_ID, scope_ref="trade",
            condition=BranchCondition(
                "bigill_channel", "门诊大额累计已达封顶→大病保险通道", "ge",
                None, "当年封顶线"),
            outcome=BranchOutcome.NOT_EVALUATED,
            reason_code="CIVIL_PAY_CHANNEL_PRESENT",
            rule_refs=("ROP-BIGILL-001",)))
    if in_bigill_channel:
        uncertainties.append(DecompositionUncertainty(
            id="u.flow.bigill_channel", code="BIGILL_CHANNEL_RULE_CANDIDATE",
            message=("门诊大额年度累计已达封顶，本单按大病保险渠道候选口径分解"
                     "（住院式：合规费用全额纳入基数×75%，先行自付个人负担 25%）；"
                     "实证 n=3（同人同日，含退费镜像），待签核。"),
            affected_fields=()))

    deductible = None
    big = None
    bigill = None
    if in_msf_channel:
        # 医事服务费通道（ROP-MSF-001）：限额内 100% 基金支付、个人无需负担起付与共付、
        # 不累计门急诊医疗待遇（不消费年度累计，不需要累计口径确认）
        big, msf_branches, msf_calcs = _msf_channel_pay(
            split.total_in_scope if split.is_complete else None)
        branches.extend(msf_branches)
        calcs.extend(msf_calcs)
        uncertainties.extend(big.uncertainties)
    elif in_bigill_channel:
        # 大病保险通道（ROP-BIGILL-001）：住院式口径重算（先行自付纳入报销基数）
        bigill = _bigill_channel_pay(split, snapshot.rounding_mode)
        branches.extend(bigill.branches)
        calcs.extend(bigill.calculations)
        uncertainties.extend(bigill.uncertainties)
    elif in_outpatient_channel:
        # 门诊大额通道：起付（区间公式）→ 大额（clamp 封顶）
        deductible = decompose_resident_deductible(
            split.total_in_scope if split.is_complete else None,
            snapshot.accumulation.prior_in_scope_fee,
            snapshot.accumulation.prior_in_scope_fee_is_pre_trade,
            tier, snapshot.trade.trade_date)
        branches.extend(deductible.branches)
        calcs.extend(deductible.calculations)
        uncertainties.extend(deductible.uncertainties)

        big = decompose_resident_big_pay(
            deductible.copay_base, tier, snapshot.trade.trade_date,
            snapshot.accumulation.prior_fund_payment,
            snapshot.accumulation.prior_fund_payment_is_pre_trade,
            snapshot.rounding_mode)
        branches.extend(big.branches)
        calcs.extend(big.calculations)
        uncertainties.extend(big.uncertainties)
    else:
        uncertainties.append(DecompositionUncertainty(
            id="u.flow.channel_unknown", code="CURE_TYPE_CHANNEL_UNKNOWN",
            message=(f"T_CureType='{cure_type}' 不在已知通道（11/19 门诊大额、17/18 医事服务费），"
                     "起付与大额支付不猜测计算。"),
            affected_fields=("T_FirstPay", "T_BigPay", "T_BigSelfPay")))

    # 8. 取整规则待确认的全局不确定性（ROP-RND-001；模式已显式传入并记录于各计算记录）
    uncertainties.append(DecompositionUncertainty(
        id="u.rounding.rule", code="ROUNDING_RULE_PENDING_CONFIRMATION",
        message=f"取整规则 ROP-RND-001 待确认；本次计算显式采用 {snapshot.rounding_mode.value}，结果不升级为已确认口径。",
        affected_fields=()))

    # 8.1 轨迹引用到的参数表规则进入 citations（带来源确认状态，未确认不升级）
    cited_rules = sorted({
        ref for b in branches for ref in b.rule_refs if ref.startswith("ROP-")
    } | {
        ref.removeprefix("rule.")
        for c in calcs for o in c.operands for ref in (o.ref,) if ref.startswith("rule.ROP-")
    })
    for rule_id in cited_rules:
        param = try_get_param(rule_id)
        if param is not None:
            citations.append(DecompositionCitation(
                id=f"rule.{rule_id}", kind="policy_document", ref=param.source,
                value=rule_id, approval_status=param.confirmation_status))
    citations.append(DecompositionCitation(
        id="fact.trade.trade_date", kind="settlement_fact",
        ref=f"snapshot:{snapshot.settlement_ref}/trade/T_TradeDate",
        value=actual_trade_date.isoformat()))

    # 9. 逐字段核对（居民口径恒等式：issue80 公式组；大病/救助渠道口径分流）
    fields, identity_calcs = _build_fields(snapshot, split, deductible, big, in_msf_channel,
                                           bigill=bigill, civil_pay_present=civil_pay_present)
    calcs.extend(identity_calcs)
    recon_status = overall_reconciliation_status(tuple(fields))

    # 10. 总体执行状态：存在 unknown/blocked 分支或目录不完整 → partial
    has_unknown = any(
        b.outcome in (BranchOutcome.UNKNOWN, BranchOutcome.BLOCKED) for b in branches)
    execution = "complete" if (split.is_complete and not has_unknown) else "partial"

    cov = coverage_counts(tuple(fields))
    return SettlementDecompositionResult(
        algorithm_version=ALGORITHM_VERSION,
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


def _classify_tier(h_level: str | None, branches: list[BranchTrace]) -> InstitutionLevelTier:
    """机构等级档分类并留痕（H_LEVEL>=10 含 14=未评级 → 一级及以下档）。"""
    from src.runtime.policy_qa.fee_decomposition.params_resident_outpatient import (
        classify_institution_tier,
    )

    tier = classify_institution_tier(h_level)
    branches.append(BranchTrace(
        step_id="institution.classify_tier", module_id="person_classification", scope_ref="trade",
        condition=BranchCondition("h_level", "机构等级档（H_LEVEL>=10 一级及以下含未评级）", "ge",
                                  h_level, "10"),
        outcome=BranchOutcome.TRUE if tier != InstitutionLevelTier.UNKNOWN else BranchOutcome.UNKNOWN,
        reason_code=None if tier != InstitutionLevelTier.UNKNOWN else "INSTITUTION_TIER_UNKNOWN",
        input_refs=("fact.institution.h_level",),
        rule_refs=("ROP-DED-001", "ROP-DED-002", "ROP-RATE-001", "ROP-RATE-002")))
    return tier


def _bigill_channel_pay(split, rounding_mode):
    """大病保险通道支付（ROP-BIGILL-001 候选口径，240914 组实证含退费镜像）。

    住院式口径：合规费用全额纳入报销基数（含先行自付），基金支付 75%、个人负担 25%：
    - BigillPay = round(FeeAll × 75%)（退费为负值镜像）
    - FeeOut（交易级）= 先行自付合计 × 25%（先行自付的 75% 由大病基金承担）
    - BigPay/FirstPay/BigSelfPay = 0（门诊大额字段不使用）
    - FundPay = BigillPay；SelfPay1 = FeeIn × 25%；SelfPayAll = FeeAll × 25%
    """
    from dataclasses import dataclass

    from src.domain.insurance.fee_decomposition import apply_rounding

    @dataclass(frozen=True)
    class BigillChannelResult:
        bigill_pay: Decimal | None
        fee_out: Decimal | None
        self_pay_2: Decimal | None
        fund_pay: Decimal | None
        self_pay_1: Decimal | None
        self_pay_all: Decimal | None
        branches: tuple[BranchTrace, ...] = ()
        calculations: tuple[CalculationRecord, ...] = ()
        uncertainties: tuple[DecompositionUncertainty, ...] = ()

    branches: list[BranchTrace] = []
    calcs: list[CalculationRecord] = []
    uncertainties: list[DecompositionUncertainty] = []
    if not split.is_complete or split.total_in_scope is None or split.total_proportional_self_pay is None:
        branches.append(BranchTrace(
            step_id="bigill.base_available", module_id="resident_bigill_pay", scope_ref="trade",
            condition=BranchCondition("in_scope_base", "医保内基数可用性", "not_null", None, "E"),
            outcome=BranchOutcome.BLOCKED, reason_code="UPSTREAM_BASE_MISSING",
            input_refs=("calc.catalog.total_in_scope",)))
        uncertainties.append(DecompositionUncertainty(
            id="u.bigill.base", code="UPSTREAM_BASE_MISSING",
            message="目录分解未得出完整基数，大病保险支付阻断。",
            affected_fields=("T_BigillPay", "T_FundPay")))
        return BigillChannelResult(None, None, None, None, None, None,
                                   tuple(branches), (), tuple(uncertainties))

    ratio = Decimal("0.75")
    total_fee = split.total_fee
    total_in = split.total_in_scope
    total_sp2 = split.total_proportional_self_pay
    eligible = total_in + total_sp2
    excluded = split.total_out_scope - total_sp2
    bigill_pay = apply_rounding(eligible * ratio, rounding_mode)
    personal_advance = apply_rounding(total_sp2 * (Decimal("1") - ratio), rounding_mode)
    fee_out = excluded + personal_advance
    self_pay_all = total_fee - bigill_pay
    # 总支付和比例自付二取整后，自付一保留差额，避免金额桶多出/少掉一分钱。
    self_pay_1 = self_pay_all - fee_out
    calcs.append(CalculationRecord(
        calculation_id="calc.bigill_pay.pay", formula_id="resident_bigill_pay_v1", formula_version="v1",
        operands=(
            CalculationOperand("calc.catalog.compliant_base", decimal_to_str(eligible)),
            CalculationOperand("rule.ROP-BIGILL-001", decimal_to_str(ratio)),
        ),
        unrounded_result=decimal_to_str(eligible * ratio),
        rounding_rule=f"explicit:{rounding_mode.value}(ROP-RND-001 待确认)",
        result=decimal_to_str(bigill_pay)))
    calcs.append(CalculationRecord(
        calculation_id="calc.bigill_pay.self_pay_2", formula_id="resident_bigill_sp2_v1",
        formula_version="v1",
        operands=(
            CalculationOperand("calc.catalog.total_proportional_self_pay", decimal_to_str(total_sp2)),
            CalculationOperand("rule.ROP-BIGILL-001", decimal_to_str(Decimal("1") - ratio)),
        ),
        unrounded_result=decimal_to_str(total_sp2 * (Decimal("1") - ratio)),
        rounding_rule=f"explicit:{rounding_mode.value}(ROP-RND-001 待确认)",
        result=decimal_to_str(personal_advance)))
    calcs.append(CalculationRecord(
        calculation_id="calc.bigill_pay.fee_out", formula_id="resident_bigill_excluded_plus_advance_v1", formula_version="v1",
        operands=(CalculationOperand("calc.catalog.excluded_fee", decimal_to_str(excluded)),
                  CalculationOperand("calc.bigill_pay.self_pay_2", decimal_to_str(personal_advance))),
        unrounded_result=decimal_to_str(fee_out), rounding_rule="not_applicable（已取整金额相加）",
        result=decimal_to_str(fee_out)))
    calcs.append(CalculationRecord(
        calculation_id="calc.bigill_pay.self_pay_1", formula_id="resident_bigill_personal_remainder_v1", formula_version="v1",
        operands=(CalculationOperand("calc.catalog.total_fee", decimal_to_str(total_fee)),
                  CalculationOperand("calc.bigill_pay.pay", decimal_to_str(bigill_pay)),
                  CalculationOperand("calc.bigill_pay.fee_out", decimal_to_str(fee_out))),
        unrounded_result=decimal_to_str(self_pay_1), rounding_rule="not_applicable（总支付后差额，保持金额守恒）",
        result=decimal_to_str(self_pay_1)))
    calcs.append(CalculationRecord(
        calculation_id="calc.bigill_pay.self_pay_all", formula_id="resident_bigill_self_pay_all_v1", formula_version="v1",
        operands=(CalculationOperand("calc.catalog.total_fee", decimal_to_str(total_fee)),
                  CalculationOperand("calc.bigill_pay.pay", decimal_to_str(bigill_pay))),
        unrounded_result=decimal_to_str(self_pay_all), rounding_rule="not_applicable（总费用减基金支付差额，无取整）",
        result=decimal_to_str(self_pay_all)))
    branches.append(BranchTrace(
        step_id="bigill.settle", module_id="resident_bigill_pay", scope_ref="trade",
        condition=BranchCondition("bigill_pay", "大病保险支付=合规费用×75%（住院式口径）", "formula",
                                  decimal_to_str(bigill_pay), "ROP-BIGILL-001"),
        outcome=BranchOutcome.TRUE, rule_refs=("ROP-BIGILL-001",),
        calculation_refs=tuple(c.calculation_id for c in calcs)))
    return BigillChannelResult(
        bigill_pay=bigill_pay, fee_out=fee_out, self_pay_2=personal_advance, fund_pay=bigill_pay,
        self_pay_1=self_pay_1, self_pay_all=self_pay_all,
        branches=tuple(branches), calculations=tuple(calcs), uncertainties=tuple(uncertainties))


def _msf_channel_pay(total_in_scope: Decimal | None):
    """医事服务费通道支付（ROP-MSF-001）：BigPay=限额内医保内费用×100%，FirstPay=0、BigSelfPay=0。

    返回 (ResidentBigPayResult, branches, calcs)：big_pay=total_in_scope、big_self_pay=0；
    基数缺失时 big_pay=None 并携带 blocked 分支与不确定性。
    """
    from src.runtime.policy_qa.fee_decomposition.resident_big_pay import ResidentBigPayResult

    branches: list[BranchTrace] = []
    calcs: list[CalculationRecord] = []
    uncertainties: list[DecompositionUncertainty] = []
    if total_in_scope is None:
        branches.append(BranchTrace(
            step_id="msf_pay.base_available", module_id="resident_msf_pay", scope_ref="trade",
            condition=BranchCondition("in_scope_base", "医保内基数可用性", "not_null", None, "E"),
            outcome=BranchOutcome.BLOCKED, reason_code="UPSTREAM_BASE_MISSING",
            input_refs=("calc.catalog.total_in_scope",)))
        uncertainties.append(DecompositionUncertainty(
            id="u.msf_pay.base", code="UPSTREAM_BASE_MISSING",
            message="目录分解未得出完整医保内基数，医事服务费支付阻断。",
            affected_fields=("T_BigPay", "T_BigSelfPay")))
        return ResidentBigPayResult(None, None, (), (), tuple(uncertainties)), tuple(branches), ()
    calc = CalculationRecord(
        calculation_id="calc.msf_pay.full", formula_id="resident_msf_full_pay_v1", formula_version="v1",
        operands=(CalculationOperand("calc.catalog.total_in_scope", decimal_to_str(total_in_scope)),
                  CalculationOperand("rule.ROP-MSF-001", "1")),
        unrounded_result=decimal_to_str(total_in_scope),
        rounding_rule="not_applicable（全额支付，无取整）",
        result=decimal_to_str(total_in_scope))
    calcs.append(calc)
    branches.append(BranchTrace(
        step_id="msf_pay.settle", module_id="resident_msf_pay", scope_ref="trade",
        condition=BranchCondition("msf_full_pay", "医事服务费限额内基金全额支付（不累计门急诊待遇）",
                                  "formula", decimal_to_str(total_in_scope), "ROP-MSF-001"),
        outcome=BranchOutcome.TRUE, rule_refs=("ROP-MSF-001",),
        calculation_refs=(calc.calculation_id,)))
    zero = Decimal("0")
    return ResidentBigPayResult(total_in_scope, zero, (), (), ()), tuple(branches), tuple(calcs)


def _no_benefit_result(
    snapshot: DecompositionSnapshot,
    branches: list[BranchTrace],
    uncertainties: list[DecompositionUncertainty],
    citations: list[DecompositionCitation],
) -> SettlementDecompositionResult:
    """无待遇全额自费交易的确定性分解：全部费用个人承担，医保内与各支付段为 0。

    正负交易统一（退费的无待遇交易为负值镜像，ROP-REF-001）。
    """
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
        # 居民口径恒等式（issue80）：SelfPay1=FeeIn−BigPay
        _identity("T_SelfPay1", _FIELD_LABELS["T_SelfPay1"], obs.self_pay_1,
                  (("T_FeeIn", obs.fee_in),
                   ("T_BigPay", obs.big_pay.copy_negate() if obs.big_pay is not None else None)),
                  calculation_id="calc.identity.self_pay_1",
                  formula_id="identity_self_pay_1_v1"),
        _identity("T_FundPay", _FIELD_LABELS["T_FundPay"] + "（=T_BigPay）", obs.fund_pay,
                  (("T_BigPay", obs.big_pay),),
                  calculation_id="calc.identity.fund_pay", formula_id="identity_fund_pay_v1"),
        _no_benefit_self_pay_all(sum_fee, obs, identity_calcs),
        _identity("T_SelfPayAll.vs_fee_all_minus_fund",
                  _FIELD_LABELS["T_SelfPayAll"] + "（对照 FeeAll-FundPay）",
                  obs.self_pay_all,
                  (("T_FeeAll", obs.fee_all),
                   ("T_FundPay", obs.fund_pay.copy_negate() if obs.fund_pay is not None else None)),
                  calculation_id="calc.identity.self_pay_all_vs_fund",
                  formula_id="identity_self_pay_all_vs_fund_v1"),
        _identity("T_SelfPayAll.channel",
                  _FIELD_LABELS["T_SelfPayAll"] + "（渠道恒等 账户+现金）",
                  obs.self_pay_all,
                  (("T_PersonCountPay", obs.person_count_pay), ("T_CashPay", obs.cash_pay)),
                  calculation_id="calc.identity.self_pay_all_channel",
                  formula_id="identity_self_pay_channel_v1"),
    ]
    for code in ("T_PersonCountPay", "T_CashPay"):
        value = obs.person_count_pay if code == "T_PersonCountPay" else obs.cash_pay
        entries.append(reconcile_field(
            code, _FIELD_LABELS[code], CheckType.DETAIL_AGGREGATION,
            None, value, BranchOutcome.UNKNOWN, "PAYMENT_CHANNEL_REPLAY_UNAVAILABLE"))
    recon_status = overall_reconciliation_status(tuple(entries))
    cov = coverage_counts(tuple(entries))
    return SettlementDecompositionResult(
        algorithm_version=ALGORITHM_VERSION,
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
        (obs.first_pay, obs.fee_out, obs.big_self_pay),
        calculation_refs=("calc.identity.self_pay_all",))


def _build_fields(
    snapshot: DecompositionSnapshot,
    split,
    deductible,
    big,
    in_msf_channel: bool,
    *,
    bigill=None,
    civil_pay_present: bool = False,
) -> tuple[list[FieldReconciliation], list[CalculationRecord]]:
    """居民门诊核对矩阵（issue80 公式组；大病/救助渠道口径分流）。

    - 门诊大额/医事服务费通道：issue80 官方公式组；
    - 大病保险通道（ROP-BIGILL-001）：住院式口径独立重算（FeeOut/SelfPay2=先行自付×25%，
      FundPay=BigillPay=FeeAll×75%，SelfPay1=FeeIn×25%，SelfPayAll=FeeAll×25%）；
    - 救助渠道存在（ROP-CIVIL-001）：FeeOut/SelfPay2/BigSelfPay 口径含救助冲抵，
      标 not_verifiable 不判定对错。

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

    in_bigill_channel = bigill is not None
    zero = Decimal("0")

    identity_calcs: list[CalculationRecord] = []

    def _identity(field_code, label, observed, operands, *, calculation_id, formula_id):
        entry, calc = _identity_entry(
            field_code, label, observed, operands,
            calculation_id=calculation_id, formula_id=formula_id)
        if calc is not None:
            identity_calcs.append(calc)
        return entry

    # 渠道分流的轨迹引用：大病通道各字段指向其最终计算记录；医事服务费通道大额支付有全额支付记录
    fee_out_refs = ("calc.bigill_pay.fee_out",) if in_bigill_channel else ()
    sp2_refs = ("calc.bigill_pay.self_pay_2",) if in_bigill_channel else ()
    if in_msf_channel:
        big_pay_refs: tuple[str, ...] = ("calc.msf_pay.full",)
    else:
        # 只指向本字段自身的基金支付记录；大额自付差额属于 T_BigSelfPay。
        big_pay_refs: tuple[str, ...] = ("calc.big_pay.capped",) if big is not None and big.calculations else ()
    big_self_pay_refs = ("calc.big_pay.self_pay",) if big is not None and big.calculations else ()

    # 医保外/自付二计算值与核对策略（渠道分流）
    if in_bigill_channel:
        fee_out_calc: Decimal | None = bigill.fee_out
        sp2_calc: Decimal | None = bigill.self_pay_2
        fee_out_outcome = BranchOutcome.TRUE if fee_out_calc is not None else BranchOutcome.UNKNOWN
    else:
        # 门诊大额通道：汇总金额引用目录逐行合计记录（页面与模型共用同一解释链）。
        fee_out_refs = ("calc.catalog.total_out_scope",)
        sp2_refs = ("calc.catalog.total_self_pay_2",)
        fee_out_calc = split.total_out_scope
        sp2_calc = split.total_self_pay_2
        fee_out_outcome = (BranchOutcome.UNKNOWN if civil_pay_present
                           else BranchOutcome.TRUE if split.is_complete else BranchOutcome.UNKNOWN)

    # 起付字段：医事服务费/大病通道不参与起付（FirstPay=0 确定性）；门诊大额通道取模块计算值
    first_pay_calc: Decimal | None
    first_pay_outcome: BranchOutcome
    if in_msf_channel or in_bigill_channel:
        first_pay_calc = zero
        first_pay_outcome = BranchOutcome.TRUE
    elif deductible is not None:
        first_pay_calc = deductible.deductible_paid
        first_pay_outcome = (
            BranchOutcome.TRUE if deductible.deductible_paid is not None else (
                deductible.branches[-1].outcome if deductible.branches else BranchOutcome.UNKNOWN))
    else:
        first_pay_calc = None
        first_pay_outcome = BranchOutcome.UNKNOWN

    if in_bigill_channel:
        big_pay_calc: Decimal | None = zero
        big_pay_outcome = BranchOutcome.TRUE
        big_self_pay_calc: Decimal | None = zero
        big_self_pay_outcome = BranchOutcome.TRUE
    else:
        big_pay_calc = big.big_pay if big is not None else None
        big_pay_outcome = BranchOutcome.TRUE if big_pay_calc is not None else BranchOutcome.UNKNOWN
        big_self_pay_calc = big.big_self_pay if big is not None else None
        big_self_pay_outcome = (
            BranchOutcome.TRUE if big_self_pay_calc is not None else BranchOutcome.UNKNOWN)
        if civil_pay_present and big_self_pay_outcome == BranchOutcome.TRUE:
            # 救助渠道：大额自付账面口径含救助承担部分，不直接比对
            big_self_pay_outcome = BranchOutcome.UNKNOWN

    entries: list[FieldReconciliation] = [
        # 总费用：明细账面 ΣFee 汇总核对；另列账面恒等 T_FeeIn+T_FeeOut 对照
        reconcile_field("T_FeeAll", _FIELD_LABELS["T_FeeAll"], CheckType.DETAIL_AGGREGATION,
                        sum_fee, obs.fee_all,
                        BranchOutcome.TRUE if sum_fee is not None else BranchOutcome.BLOCKED,
                        calculation_refs=("calc.catalog.total_fee",)),
        _identity("T_FeeAll.identity", _FIELD_LABELS["T_FeeAll"] + "（账面恒等 In+Out）",
                  obs.fee_all, (("T_FeeIn", obs.fee_in), ("T_FeeOut", obs.fee_out)),
                  calculation_id="calc.identity.fee_all", formula_id="identity_fee_all_v1"),
        # 医保内：独立目录分解 vs 交易账面；另列明细账面汇总
        reconcile_field("T_FeeIn", _FIELD_LABELS["T_FeeIn"], CheckType.INDEPENDENT_RECALCULATION,
                        split.total_in_scope, obs.fee_in,
                        BranchOutcome.TRUE if split.is_complete else BranchOutcome.UNKNOWN,
                        calculation_refs=("calc.catalog.total_in_scope",)),
        reconcile_field("T_FeeIn.detail", _FIELD_LABELS["T_FeeIn"] + "（明细账面汇总）",
                        CheckType.DETAIL_AGGREGATION,
                        sum_book_in if book_in_complete else None, obs.fee_in,
                        BranchOutcome.TRUE if book_in_complete else BranchOutcome.UNKNOWN),
        reconcile_field("T_FeeOut", _FIELD_LABELS["T_FeeOut"], CheckType.INDEPENDENT_RECALCULATION,
                        fee_out_calc, obs.fee_out, fee_out_outcome,
                        "CIVIL_PAY_CHANNEL_PRESENT" if civil_pay_present else None,
                        calculation_refs=fee_out_refs),
        reconcile_field("T_FeeOut.detail", _FIELD_LABELS["T_FeeOut"] + "（明细账面汇总）",
                        CheckType.DETAIL_AGGREGATION,
                        sum_book_out if book_out_complete else None, obs.fee_out,
                        BranchOutcome.TRUE if book_out_complete else BranchOutcome.UNKNOWN),
        # 自付二：独立逐行计算 vs 交易账面；明细账面汇总另列
        reconcile_field("T_SelfPay2", _FIELD_LABELS["T_SelfPay2"], CheckType.INDEPENDENT_RECALCULATION,
                        sp2_calc, obs.self_pay_2, fee_out_outcome,
                        "CIVIL_PAY_CHANNEL_PRESENT" if civil_pay_present else None,
                        calculation_refs=sp2_refs),
        reconcile_field("T_SelfPay2.detail", _FIELD_LABELS["T_SelfPay2"] + "（明细账面汇总）",
                        CheckType.DETAIL_AGGREGATION,
                        sum_book_sp2 if book_sp2_complete else None, obs.self_pay_2,
                        BranchOutcome.TRUE if book_sp2_complete else BranchOutcome.UNKNOWN),
        # 起付/大额
        reconcile_field("T_FirstPay", _FIELD_LABELS["T_FirstPay"], CheckType.INDEPENDENT_RECALCULATION,
                        first_pay_calc, obs.first_pay, first_pay_outcome,
                        calculation_refs=tuple(c.calculation_id for c in deductible.calculations)
                        if deductible is not None else ()),
        reconcile_field("T_BigPay", _FIELD_LABELS["T_BigPay"], CheckType.INDEPENDENT_RECALCULATION,
                        big_pay_calc, obs.big_pay, big_pay_outcome,
                        calculation_refs=big_pay_refs),
        reconcile_field("T_BigSelfPay", _FIELD_LABELS["T_BigSelfPay"],
                        CheckType.INDEPENDENT_RECALCULATION,
                        big_self_pay_calc, obs.big_self_pay, big_self_pay_outcome,
                        "CIVIL_PAY_CHANNEL_PRESENT" if civil_pay_present else None,
                        calculation_refs=big_self_pay_refs),
        # 大病保险支付：大病通道独立重算；其他通道不适用（账面非零另报冲突）
        reconcile_field("T_BigillPay", _FIELD_LABELS["T_BigillPay"],
                        CheckType.INDEPENDENT_RECALCULATION,
                        bigill.bigill_pay if in_bigill_channel else None, obs.bigill_pay,
                        BranchOutcome.TRUE if (in_bigill_channel and bigill.bigill_pay is not None)
                        else (BranchOutcome.UNKNOWN if in_bigill_channel
                              else BranchOutcome.NOT_APPLICABLE),
                        None if in_bigill_channel else "RESIDENT_BIGILL_NOT_APPLICABLE",
                        calculation_refs=("calc.bigill_pay.pay",) if in_bigill_channel else ()),
        # 补充待遇：居民无退休/军残/公疗补充（账面非零另报资格与账面冲突）
        reconcile_field("T_BCPay", _FIELD_LABELS["T_BCPay"] + "（居民不适用）",
                        CheckType.INDEPENDENT_RECALCULATION,
                        None, obs.bc_pay, BranchOutcome.NOT_APPLICABLE,
                        "RESIDENT_SUPPLEMENT_NOT_APPLICABLE"),
        reconcile_field("T_JCPay", _FIELD_LABELS["T_JCPay"] + "（居民不适用）",
                        CheckType.INDEPENDENT_RECALCULATION,
                        None, obs.jc_pay, BranchOutcome.NOT_APPLICABLE,
                        "RESIDENT_SUPPLEMENT_NOT_APPLICABLE"),
        reconcile_field("T_OfficalPay", _FIELD_LABELS["T_OfficalPay"] + "（居民不适用）",
                        CheckType.INDEPENDENT_RECALCULATION,
                        None, obs.official_pay, BranchOutcome.NOT_APPLICABLE,
                        "RESIDENT_SUPPLEMENT_NOT_APPLICABLE"),
    ]

    if in_bigill_channel:
        # 大病通道：FundPay/SelfPay1/SelfPayAll 独立重算（住院式口径）
        entries.append(reconcile_field(
            "T_FundPay", _FIELD_LABELS["T_FundPay"] + "（=大病保险支付）",
            CheckType.INDEPENDENT_RECALCULATION,
            bigill.fund_pay, obs.fund_pay,
            BranchOutcome.TRUE if bigill.fund_pay is not None else BranchOutcome.UNKNOWN,
            calculation_refs=("calc.bigill_pay.pay",)))
        entries.append(reconcile_field(
            "T_SelfPay1", _FIELD_LABELS["T_SelfPay1"] + "（=医保内×25%）",
            CheckType.INDEPENDENT_RECALCULATION,
            bigill.self_pay_1, obs.self_pay_1,
            BranchOutcome.TRUE if bigill.self_pay_1 is not None else BranchOutcome.UNKNOWN,
            calculation_refs=("calc.bigill_pay.self_pay_1",)))
        entries.append(reconcile_field(
            "T_SelfPayAll", _FIELD_LABELS["T_SelfPayAll"] + "（=总费用×25%）",
            CheckType.INDEPENDENT_RECALCULATION,
            bigill.self_pay_all, obs.self_pay_all,
            BranchOutcome.TRUE if bigill.self_pay_all is not None else BranchOutcome.UNKNOWN,
            calculation_refs=("calc.bigill_pay.self_pay_all",)))
    else:
        # 自付一 = 起付 + 大额自付（两项均由本单独立计算）；分量缺失才退回账面恒等
        if deductible is not None and big is not None and deductible.deductible_paid is not None                 and big.big_self_pay is not None:
            self_pay_1 = deductible.deductible_paid + big.big_self_pay
            identity_calcs.append(CalculationRecord(
                calculation_id="calc.self_pay_1.parts", formula_id="self_pay_1_components_v1",
                formula_version="v1",
                operands=(
                    CalculationOperand("calc.deductible.split", decimal_to_str(deductible.deductible_paid)),
                    CalculationOperand("calc.big_pay.self_pay", decimal_to_str(big.big_self_pay)),
                ),
                unrounded_result=decimal_to_str(self_pay_1),
                rounding_rule="not_applicable（加法，无取整）",
                result=decimal_to_str(self_pay_1)))
            entries.append(reconcile_field(
                "T_SelfPay1", _FIELD_LABELS["T_SelfPay1"], CheckType.INDEPENDENT_RECALCULATION,
                self_pay_1, obs.self_pay_1, BranchOutcome.TRUE,
                calculation_refs=("calc.self_pay_1.parts",)))
        else:
            entries.append(_identity(
                "T_SelfPay1", _FIELD_LABELS["T_SelfPay1"] + "（=医保内−大额支付）", obs.self_pay_1,
                (("T_FeeIn", obs.fee_in),
                 ("T_BigPay", obs.big_pay.copy_negate() if obs.big_pay is not None else None)),
                calculation_id="calc.identity.self_pay_1", formula_id="identity_self_pay_1_v1"))
        # 基金合计恒等：T_FundPay = T_BigPay（+大病/救助渠道观测分量，若有）
        fund_operands: list[tuple[str, Decimal | None]] = [("T_BigPay", obs.big_pay)]
        fund_label = "（=T_BigPay）"
        if obs.bigill_pay is not None and obs.bigill_pay != 0:
            fund_operands.append(("T_BigillPay", obs.bigill_pay))
            fund_label = "（=T_BigPay+T_BigillPay）"
        if civil_pay_present:
            fund_operands.append(("NT_CivilPay", obs.civil_pay))
            fund_label = "（=T_BigPay+NT_CivilPay）" if obs.bigill_pay is None else fund_label
        entries.append(_identity(
            "T_FundPay", _FIELD_LABELS["T_FundPay"] + fund_label, obs.fund_pay,
            tuple(fund_operands),
            calculation_id="calc.identity.fund_pay", formula_id="identity_fund_pay_v1"))
        components = (
            deductible.deductible_paid if deductible is not None else None,
            split.total_out_scope,
            big.big_self_pay if big is not None else None,
        )
        if all(value is not None for value in components):
            total = sum(components, Decimal("0"))  # type: ignore[arg-type]
            identity_calcs.append(CalculationRecord(
                calculation_id="calc.self_pay_all.parts", formula_id="self_pay_all_components_v1",
                formula_version="v1",
                operands=(
                    CalculationOperand("calc.deductible.split", decimal_to_str(components[0])),
                    CalculationOperand("calc.catalog.total_out_scope", decimal_to_str(components[1])),
                    CalculationOperand("calc.big_pay.self_pay", decimal_to_str(components[2])),
                ),
                unrounded_result=decimal_to_str(total),
                rounding_rule="not_applicable（加法，无取整）",
                result=decimal_to_str(total)))
            entries.append(reconcile_field(
                "T_SelfPayAll", _FIELD_LABELS["T_SelfPayAll"], CheckType.INDEPENDENT_RECALCULATION,
                total, obs.self_pay_all, BranchOutcome.TRUE,
                calculation_refs=("calc.self_pay_all.parts",)))
        else:
            entries.append(_identity(
                "T_SelfPayAll", _FIELD_LABELS["T_SelfPayAll"] + "（=起付+医保外+大额自付）",
                obs.self_pay_all,
                (("T_FirstPay", obs.first_pay), ("T_FeeOut", obs.fee_out),
                 ("T_BigSelfPay", obs.big_self_pay)),
                calculation_id="calc.identity.self_pay_all", formula_id="identity_self_pay_all_v1"))
    entries.append(_identity(
        "T_SelfPayAll.vs_fee_all_minus_fund",
        _FIELD_LABELS["T_SelfPayAll"] + "（对照 FeeAll-FundPay）",
        obs.self_pay_all,
        (("T_FeeAll", obs.fee_all),
         ("T_FundPay", obs.fund_pay.copy_negate() if obs.fund_pay is not None else None)),
        calculation_id="calc.identity.self_pay_all_vs_fund",
        formula_id="identity_self_pay_all_vs_fund_v1"))
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
