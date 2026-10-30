"""城乡居民门特（门诊特殊病·按项目付费，mz 套表）费用分解流程编排（Issue #81）。

与职工门特（employee_outpatient_special，Issue #79）的关系：
- 复用：mz 套表读取骨架（locate/load/derive 交易后口径推导模式）、周期上下文三态、
  快照值对象（OutpatientSpecialSnapshot 族）、核对框架与结果契约；
- 差异 1：**目录独立分解**（Issue #81 明确要求，职工门特本期直接用账面 ybnje/ybwje）——
  明细经 ``resident_special_catalog`` 适配复用 ``split_catalog``（与居民门诊同规则），
  独立重算 tsbybn/tsbybw/grziftw 并与账面核对；
- 差异 2：居民门特**无统筹分段**（tczhf/tczif 恒 0，RSP-POOL-001）、**无退休/军残/公疗
  补充待遇**（not_applicable），起付按人员类别×机构档×周期位置三维选择（RSP-DED），
  基本基金支付按机构档比例（三级 75%/二级 78%/一级 80%）clamp 年度基金封顶（25 万，2019 起）；
- 非特殊病费用（ptybn/ptybw≠0，按普通门诊结算）本期不支持，快照服务层前置拦截
  （同职工 ESP-CAT-002 口径）。

支付公式（issue81 + 实证闭合）：
    ybnqfje  = min(tsbybn, max(D − 周期内已交起付, 0))
    degwyzhf = clamp(round((tsbybn − ybnqfje) × rate), −prior_large, max(cap − prior_large, 0))
    degwyzif = (tsbybn − ybnqfje) − degwyzhf
    tczhf = tczif = 0
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    BranchCondition,
    BranchOutcome,
    BranchTrace,
    CalculationOperand,
    CalculationRecord,
    CheckType,
    DecompositionCitation,
    DecompositionUncertainty,
    FieldReconciliation,
    OutpatientSpecialSnapshot,
    apply_rounding,
    decimal_to_str,
)
from src.runtime.policy_qa.fee_decomposition.params_resident_outpatient_special import (
    institution_level_from_h_level,
    select_resident_special_big_pay_rate_param,
    select_resident_special_cap_param,
    select_resident_special_deductible_param,
    try_get_param,
)
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

_MODULE_ID = "resident_outpatient_special"
ALGORITHM_VERSION = "resident_outpatient_special_v1"

_FIELD_LABELS = {
    "ZJE": "总费用",
    "PTYBN": "普通门诊医保内",
    "PTYBW": "普通门诊医保外",
    "TSBYBN": "特殊病医保内",
    "TSBYBW": "特殊病医保外",
    "YBNQFJE": "本次起付金额",
    "GRZIFTW": "个人自付二（先行自付）",
    "GRZIF1": "个人支付自付（一）金额",
    "TCZHF": "统筹基金支付",
    "TCZIF": "统筹自付",
    "DEGWYZHF": "基本医保基金支付",
    "DEGWYZIF": "基本医保基金支付后自付",
    "BCZHF": "退休补助",
    "JCZHF": "军残补助",
    "GFYLBCHBX": "公疗补助",
    "XJZF": "现金支付",
    "ZHZF": "账户支付",
}


@dataclass(frozen=True)
class _FundOutcome:
    """居民门特基本医保基金计算结果。"""

    big_pay: Decimal | None
    big_self_pay: Decimal | None
    branches: tuple[BranchTrace, ...] = ()
    calculations: tuple[CalculationRecord, ...] = ()
    uncertainties: tuple[DecompositionUncertainty, ...] = ()


@dataclass(frozen=True)
class _DeductibleOutcome:
    """起付计算结果。"""

    deductible_paid: Decimal | None
    branches: tuple[BranchTrace, ...] = ()
    calculations: tuple[CalculationRecord, ...] = ()
    uncertainties: tuple[DecompositionUncertainty, ...] = ()


def _empty_result(
    snapshot: OutpatientSpecialSnapshot,
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


def _base_citations(snapshot: OutpatientSpecialSnapshot) -> list[DecompositionCitation]:
    return [
        DecompositionCitation(
            id="rule.person_type_codes.issue81", kind="issue_note",
            ref="https://github.com/ktyhwangfei/hospital_medical_insurance_agent/issues/81",
            approval_status="pending"),
        DecompositionCitation(
            id="fact.settlement.settle_date", kind="settlement_fact",
            ref=f"snapshot:{snapshot.settlement_ref}/settlement/jyrq",
            value=snapshot.settle_date.isoformat()),
    ]


def _decompose_deductible(
    snapshot: OutpatientSpecialSnapshot,
    total_in_scope: Decimal | None,
    institution_level: str | None,
) -> _DeductibleOutcome:
    """起付分解：ybnqfje = min(tsbybn, max(D − 周期内已交起付, 0))。

    硬约束：周期证据非 confirmed（累计口径不明）或起付标准不能确定 → unknown，不硬算；
    账面 ybnqfje 仅作核对目标，不用于反推。
    """
    branches: list[BranchTrace] = []
    calcs: list[CalculationRecord] = []
    uncertainties: list[DecompositionUncertainty] = []
    module = "resident_special_deductible"

    if total_in_scope is None:
        branches.append(BranchTrace(
            step_id="deductible.base_available", module_id=module, scope_ref="settlement",
            condition=BranchCondition("in_scope_base", "特殊病医保内基数可用性", "not_null",
                                      None, "E"),
            outcome=BranchOutcome.BLOCKED, reason_code="UPSTREAM_BASE_MISSING",
            input_refs=("calc.catalog.total_in_scope",)))
        uncertainties.append(DecompositionUncertainty(
            id="u.deductible.base", code="UPSTREAM_BASE_MISSING",
            message="目录分解未得出完整特殊病医保内基数，起付分解阻断。",
            affected_fields=("YBNQFJE", "DEGWYZHF", "DEGWYZIF")))
        return _DeductibleOutcome(None, tuple(branches), (), tuple(uncertainties))

    if "CYCLE_TABLE_LAGGING" in snapshot.cycle.evidence_note:
        uncertainties.append(DecompositionUncertainty(
            id="u.cycle.lagging", code="CYCLE_TABLE_LAGGING",
            message="年度快照疑似滞后，原累计不能证实为交易前口径；依赖字段不硬算。",
            affected_fields=("DEGWYZHF", "DEGWYZIF", "BIG_ILL_PAY", "CIVIL_IN", "PERSON_PAYABLE")))
    if not snapshot.cycle.is_confirmed("cycle_position", "prior_cycle_deductible_paid"):
        branches.append(BranchTrace(
            step_id="deductible.cycle_evidence", module_id=module, scope_ref="settlement",
            condition=BranchCondition("cycle_evidence", "周期上下文证据三态", "eq",
                                      snapshot.cycle.evidence_status, "confirmed"),
            outcome=BranchOutcome.UNKNOWN, reason_code="CYCLE_EVIDENCE_NOT_CONFIRMED",
            input_refs=("fact.cycle.evidence",)))
        uncertainties.append(DecompositionUncertainty(
            id="u.deductible.cycle", code="CYCLE_EVIDENCE_NOT_CONFIRMED",
            message=f"周期/年度累计证据不足（{snapshot.cycle.evidence_note}），起付与大额字段不硬算。",
            affected_fields=("YBNQFJE", "DEGWYZHF", "DEGWYZIF")))
        return _DeductibleOutcome(None, tuple(branches), (), tuple(uncertainties))

    assert snapshot.cycle.cycle_position is not None
    sel = select_resident_special_deductible_param(
        snapshot.person.cblb, institution_level,
        snapshot.cycle.cycle_position, snapshot.settle_date)
    branches.append(BranchTrace(
        step_id="deductible.param_select", module_id=module, scope_ref="settlement",
        condition=BranchCondition("deductible_param", "起付标准选择（人员×机构档×周期位置）",
                                  "select",
                                  f"{snapshot.person.cblb}/{institution_level}/{snapshot.cycle.cycle_position}",
                                  "RSP-DED 系列"),
        outcome=sel.outcome, reason_code=sel.reason_code,
        rule_refs=("RSP-DED-001", "RSP-DED-002", "RSP-DED-003",
                   "RSP-DED-101", "RSP-DED-102", "RSP-DED-103", "RSP-DED-104")))
    if sel.outcome != BranchOutcome.TRUE or sel.param is None or sel.param.value is None:
        uncertainties.append(DecompositionUncertainty(
            id="u.deductible.param", code=sel.reason_code or "PARAM_VERSION_NOT_FOUND",
            message="适用门特起付标准不能确定，不采用默认值。",
            affected_fields=("YBNQFJE",)))
        return _DeductibleOutcome(None, tuple(branches), (), tuple(uncertainties))
    standard = sel.param.value

    prior_paid = snapshot.cycle.prior_cycle_deductible_paid
    if prior_paid is None:
        branches.append(BranchTrace(
            step_id="deductible.prior_paid", module_id=module, scope_ref="settlement",
            condition=BranchCondition("prior_cycle_deductible", "周期内交易前已交起付", "not_null",
                                      None, "A"),
            outcome=BranchOutcome.UNKNOWN, reason_code="PRIOR_DEDUCTIBLE_MISSING",
            input_refs=("fact.cycle.prior_cycle_deductible_paid",)))
        uncertainties.append(DecompositionUncertainty(
            id="u.deductible.prior", code="PRIOR_DEDUCTIBLE_MISSING",
            message="周期内已交起付未知，本次起付不能独立计算。",
            affected_fields=("YBNQFJE",)))
        return _DeductibleOutcome(None, tuple(branches), (), tuple(uncertainties))

    paid = min(total_in_scope, max(standard - prior_paid, Decimal("0")))
    calc = CalculationRecord(
        calculation_id="calc.deductible.split", formula_id="resident_special_deductible_v1",
        formula_version="v1",
        operands=(
            CalculationOperand("calc.catalog.total_in_scope", decimal_to_str(total_in_scope)),
            CalculationOperand("fact.cycle.prior_cycle_deductible_paid", decimal_to_str(prior_paid)),
            CalculationOperand(f"rule.{sel.param.rule_id}", decimal_to_str(standard)),
        ),
        unrounded_result=decimal_to_str(paid),
        rounding_rule="not_applicable（min/max 运算，无取整）",
        result=decimal_to_str(paid))
    calcs.append(calc)
    calcs.append(CalculationRecord(
        calculation_id="calc.deductible.copay_base", formula_id="copay_base_v1", formula_version="v1",
        operands=(CalculationOperand("calc.catalog.total_in_scope", decimal_to_str(total_in_scope)),
                  CalculationOperand("calc.deductible.split", decimal_to_str(paid))),
        result=decimal_to_str(total_in_scope - paid), rounding_rule="not_applicable"))
    branches.append(BranchTrace(
        step_id="deductible.split", module_id=module, scope_ref="settlement",
        condition=BranchCondition("deductible_split",
                                  "本次起付 ybnqfje=min(E,max(D−A,0))", "formula",
                                  decimal_to_str(paid),
                                  f"E={decimal_to_str(total_in_scope)},A={decimal_to_str(prior_paid)},D={decimal_to_str(standard)}"),
        outcome=BranchOutcome.TRUE,
        rule_refs=(sel.param.rule_id,),
        input_refs=("calc.catalog.total_in_scope", "fact.cycle.prior_cycle_deductible_paid"),
        calculation_refs=(calc.calculation_id,)))
    return _DeductibleOutcome(paid, tuple(branches), tuple(calcs), tuple(uncertainties))


def _compute_big_pay(
    snapshot: OutpatientSpecialSnapshot,
    total_in_scope: Decimal | None,
    deductible_paid: Decimal | None,
    institution_level: str | None,
) -> _FundOutcome:
    """基本医保基金支付：degwyzhf = clamp(round((E−F)×rate), −prior_large, max(cap−prior_large, 0))。"""
    branches: list[BranchTrace] = []
    calcs: list[CalculationRecord] = []
    uncertainties: list[DecompositionUncertainty] = []
    module = "resident_special_big_pay"

    if total_in_scope is None or deductible_paid is None:
        branches.append(BranchTrace(
            step_id="big_pay.base_available", module_id=module, scope_ref="settlement",
            condition=BranchCondition("copay_base", "基本基金基数（E−F）可用性", "not_null",
                                      None, "B"),
            outcome=BranchOutcome.BLOCKED, reason_code="UPSTREAM_BASE_MISSING",
            input_refs=("calc.deductible.split",)))
        uncertainties.append(DecompositionUncertainty(
            id="u.big_pay.base", code="UPSTREAM_BASE_MISSING",
            message="起付分解未得出基本基金基数，基本基金支付阻断。",
            affected_fields=("DEGWYZHF", "DEGWYZIF")))
        return _FundOutcome(None, None, tuple(branches), (), tuple(uncertainties))
    base = total_in_scope - deductible_paid

    sel = select_resident_special_big_pay_rate_param(institution_level, snapshot.settle_date)
    branches.append(BranchTrace(
        step_id="big_pay.rate_select", module_id=module, scope_ref="settlement",
        condition=BranchCondition("big_pay_rate", "基本基金支付比例档选择（机构档）", "select",
                                  f"{institution_level}@{snapshot.settle_date.isoformat()}",
                                  "RSP-RATE-001/002/003"),
        outcome=sel.outcome, reason_code=sel.reason_code,
        rule_refs=("RSP-RATE-001", "RSP-RATE-002", "RSP-RATE-003")))
    if sel.outcome != BranchOutcome.TRUE or sel.param is None or sel.param.ratio is None:
        uncertainties.append(DecompositionUncertainty(
            id="u.big_pay.rate", code=sel.reason_code or "PARAM_VERSION_NOT_FOUND",
            message="适用基本基金支付比例档不能确定，不采用默认比例。",
            affected_fields=("DEGWYZHF", "DEGWYZIF")))
        return _FundOutcome(None, None, tuple(branches), (), tuple(uncertainties))
    rate = sel.param.ratio

    cap_sel = select_resident_special_cap_param(snapshot.settle_date)
    branches.append(BranchTrace(
        step_id="big_pay.cap_regime", module_id=module, scope_ref="settlement",
        condition=BranchCondition("cap_regime", "年度基金封顶规则适用", "select",
                                  snapshot.settle_date.isoformat(), "RSP-CAP-001/002"),
        outcome=cap_sel.outcome, reason_code=cap_sel.reason_code,
        rule_refs=("RSP-CAP-001", "RSP-CAP-002")))
    if cap_sel.outcome != BranchOutcome.TRUE or cap_sel.param is None or cap_sel.param.value is None:
        uncertainties.append(DecompositionUncertainty(
            id="u.big_pay.cap", code=cap_sel.reason_code or "PARAM_VERSION_NOT_FOUND",
            message="年度基金封顶规则不能确定。", affected_fields=("DEGWYZHF", "DEGWYZIF")))
        return _FundOutcome(None, None, tuple(branches), (), tuple(uncertainties))
    cap = cap_sel.param.value

    prior_large = snapshot.cycle.prior_annual_large_fund_payment
    if not snapshot.cycle.is_confirmed("prior_annual_large_fund_payment"):
        branches.append(BranchTrace(
            step_id="big_pay.fund_cumulative", module_id=module, scope_ref="settlement",
            condition=BranchCondition("prior_large_fund", "交易前年度大额累计可用且口径已确认",
                                      "confirmed",
                                      decimal_to_str(prior_large) if prior_large is not None else None,
                                      "大额基金累计（交易前）"),
            outcome=BranchOutcome.UNKNOWN,
            reason_code="FUND_CUMULATIVE_MISSING" if prior_large is None
            else "FUND_CUMULATIVE_CALIBER_UNCONFIRMED",
            input_refs=("fact.cycle.prior_annual_large_fund_payment",)))
        uncertainties.append(DecompositionUncertainty(
            id="u.big_pay.fund_cumulative",
            code=branches[-1].reason_code or "FUND_CUMULATIVE_MISSING",
            message="缺少交易前年度大额累计（或口径未确认），封顶切档不能确定。",
            affected_fields=("DEGWYZHF", "DEGWYZIF")))
        return _FundOutcome(None, None, tuple(branches), (), tuple(uncertainties))

    assert prior_large is not None
    upper = max(cap - prior_large, Decimal("0"))
    lower = -prior_large
    raw_unrounded = base * rate
    raw = apply_rounding(raw_unrounded, snapshot.rounding_mode)
    pay = min(max(raw, lower), upper)
    # 封顶余额：封顶线−交易前已支付，供“还能报多少”引用（模型不得自行做减法）。
    calcs.append(CalculationRecord(
        calculation_id="calc.big_pay.cap_room", formula_id="cap_room_v1", formula_version="v1",
        operands=(
            CalculationOperand(f"rule.{cap_sel.param.rule_id}", decimal_to_str(cap)),
            CalculationOperand("fact.cycle.prior_annual_large_fund_payment",
                               decimal_to_str(prior_large)),
        ),
        unrounded_result=decimal_to_str(cap - prior_large),
        rounding_rule="not_applicable（减法运算，无取整）",
        result=decimal_to_str(upper)))
    calcs.append(CalculationRecord(
        calculation_id="calc.big_pay.capped", formula_id="resident_special_big_pay_clamp_v1",
        formula_version="v1",
        operands=(
            CalculationOperand("calc.deductible.copay_base", decimal_to_str(base)),
            CalculationOperand(f"rule.{sel.param.rule_id}", decimal_to_str(rate)),
            CalculationOperand("fact.cycle.prior_annual_large_fund_payment",
                               decimal_to_str(prior_large)),
            CalculationOperand(f"rule.{cap_sel.param.rule_id}", decimal_to_str(cap)),
            CalculationOperand("calc.big_pay.cap_room", decimal_to_str(upper)),
        ),
        unrounded_result=decimal_to_str(raw_unrounded),
        rounding_rule=f"explicit:{snapshot.rounding_mode.value}(RSP-RND-001 待确认)",
        result=decimal_to_str(pay)))
    big_self_pay = base - pay
    calcs.append(CalculationRecord(
        calculation_id="calc.big_pay.self_pay", formula_id="big_self_pay_v1", formula_version="v1",
        operands=(
            CalculationOperand("calc.deductible.copay_base", decimal_to_str(base)),
            CalculationOperand("calc.big_pay", decimal_to_str(pay)),
        ),
        unrounded_result=decimal_to_str(big_self_pay),
        rounding_rule="not_applicable（减法运算，无取整）",
        result=decimal_to_str(big_self_pay)))
    branches.append(BranchTrace(
        step_id="big_pay.settle", module_id=module, scope_ref="settlement",
        condition=BranchCondition("big_pay_settle",
                                  "degwyzhf=clamp((E−F)×比例, −大额已付, 封顶−大额已付)",
                                  "formula", decimal_to_str(pay), None),
        outcome=BranchOutcome.TRUE,
        rule_refs=(sel.param.rule_id, cap_sel.param.rule_id),
        calculation_refs=tuple(c.calculation_id for c in calcs)))
    return _FundOutcome(pay, big_self_pay, tuple(branches), tuple(calcs), tuple(uncertainties))


def decompose_resident_outpatient_special(
    snapshot: OutpatientSpecialSnapshot,
    catalog_split_result=None,
) -> SettlementDecompositionResult:
    """城乡居民门特（按项目付费，mz 套表）费用分解主流程。

    catalog_split_result：目录独立分解结果（resident_special_catalog 产出）；
    None 时 tsbybn/tsbybw/grziftw 不独立重算（降级 partial，不猜测）。
    """
    branches: list[BranchTrace] = []
    calcs: list[CalculationRecord] = []
    uncertainties: list[DecompositionUncertainty] = []
    citations = _base_citations(snapshot)

    # 1. 组合选择：仅居民+门特
    supported = (snapshot.insurance_type == "resident"
                 and snapshot.medical_category == "outpatient_special")
    branches.append(BranchTrace(
        step_id="flow.profile_select", module_id=_MODULE_ID, scope_ref="settlement",
        condition=BranchCondition("profile", "险种×医疗类别组合", "eq",
                                  f"{snapshot.insurance_type}+{snapshot.medical_category}",
                                  "resident+outpatient_special"),
        outcome=BranchOutcome.TRUE if supported else BranchOutcome.NOT_APPLICABLE,
        reason_code=None if supported else "UNSUPPORTED_PROFILE",
        rule_refs=("RSP-CAT-001",)))
    if not supported:
        uncertainties.append(DecompositionUncertainty(
            id="u.flow.unsupported_profile", code="UNSUPPORTED_PROFILE",
            message="本流程仅支持城乡居民×门诊特殊病（按项目付费）；其他组合尚不支持，不套用门特公式。",
            affected_fields=()))
        return _empty_result(snapshot, "unavailable", branches, uncertainties, citations)

    # 2. 明细行键重复/负金额检查：数据异常或未支持重算（mz 套表退费规则未确认）
    line_keys = [it.line_key for it in snapshot.items]
    if len(line_keys) != len(set(line_keys)):
        branches.append(BranchTrace(
            step_id="flow.duplicate_key_check", module_id=_MODULE_ID, scope_ref="settlement",
            condition=BranchCondition("duplicate_line_key", "明细行键（xh）唯一", "unique",
                                      None, "无重复"),
            outcome=BranchOutcome.FALSE, reason_code="DUPLICATE_LINE_KEY"))
        uncertainties.append(DecompositionUncertainty(
            id="u.flow.duplicate_key", code="DUPLICATE_LINE_KEY",
            message="费用明细存在重复行键，属数据异常，未静默去重。",
            affected_fields=tuple(_FIELD_LABELS)))
        return _empty_result(snapshot, "unavailable", branches, uncertainties, citations)
    has_negative = any(
        it.fee < 0
        or (it.quantity is not None and it.quantity < 0)
        or (it.in_scope_fee is not None and it.in_scope_fee < 0)
        or (it.out_scope_fee is not None and it.out_scope_fee < 0)
        for it in snapshot.items)
    branches.append(BranchTrace(
        step_id="flow.negative_check", module_id=_MODULE_ID, scope_ref="settlement",
        condition=BranchCondition("negative_amount", "负金额/负数量明细", "eq",
                                  str(has_negative).lower(), "false"),
        outcome=BranchOutcome.FALSE if has_negative else BranchOutcome.TRUE,
        reason_code="UNSUPPORTED_REVERSAL_OR_NEGATIVE" if has_negative else None))
    if has_negative:
        uncertainties.append(DecompositionUncertainty(
            id="u.flow.negative", code="UNSUPPORTED_REVERSAL_OR_NEGATIVE",
            message="负金额/负数量明细进入未支持重算状态，不取绝对值套正向公式。",
            affected_fields=tuple(_FIELD_LABELS)))
        return _empty_result(snapshot, "unavailable", branches, uncertainties, citations)

    # 3. 机构等级分类（住院口径：01-05 三级 / 06-09 二级 / 10+ 一级及未评级）
    institution_level = institution_level_from_h_level(snapshot.institution.h_level)
    branches.append(BranchTrace(
        step_id="institution.classify", module_id="person_classification", scope_ref="settlement",
        condition=BranchCondition("h_level", "机构等级（住院口径档）", "in",
                                  snapshot.institution.h_level, "01-05=3/06-09=2/10+=1"),
        outcome=BranchOutcome.TRUE if institution_level is not None else BranchOutcome.UNKNOWN,
        reason_code=None if institution_level is not None else "INSTITUTION_LEVEL_UNKNOWN",
        input_refs=("fact.institution.h_level",),
        rule_refs=("RSP-DED-001", "RSP-RATE-001")))

    # 4. 目录独立分解（Issue #81；与账面 tsbybn/tsbybw/grziftw 核对）
    split = catalog_split_result
    if split is None:
        uncertainties.append(DecompositionUncertainty(
            id="u.catalog.missing", code="CATALOG_SPLIT_NOT_PROVIDED",
            message="目录独立分解结果未提供，tsbybn/tsbybw/grziftw 不独立重算。",
            affected_fields=("TSBYBN", "TSBYBW", "GRZIFTW")))
        total_in_scope = None
    else:
        branches.extend(split.branches)
        calcs.extend(split.calculations)
        uncertainties.extend(split.uncertainties)
        if split.fatal_issue is not None:
            return _empty_result(snapshot, "unavailable", branches, uncertainties, citations)
        total_in_scope = split.total_in_scope if split.is_complete else None

    # 5. 起付（周期上下文 confirmed + RSP-DED 三维选择）
    deductible = _decompose_deductible(snapshot, total_in_scope, institution_level)
    branches.extend(deductible.branches)
    calcs.extend(deductible.calculations)
    uncertainties.extend(deductible.uncertainties)

    # 6. 统筹：居民门特不设统筹分段（RSP-POOL-001，确定性 0）
    branches.append(BranchTrace(
        step_id="pool.not_applicable", module_id="resident_special_pool", scope_ref="settlement",
        condition=BranchCondition("pool_channel", "统筹分段适用性（居民门特）", "eq",
                                  "0", "tczhf/tczif 恒 0"),
        outcome=BranchOutcome.TRUE,
        rule_refs=("RSP-POOL-001",)))

    # 7. 基本医保基金支付（机构档比例 clamp 年度封顶）
    funds = _compute_big_pay(snapshot, total_in_scope, deductible.deductible_paid,
                             institution_level)
    branches.extend(funds.branches)
    calcs.extend(funds.calculations)
    uncertainties.extend(funds.uncertainties)

    # 8. 取整规则待确认的全局不确定性（RSP-RND-001）
    uncertainties.append(DecompositionUncertainty(
        id="u.rounding.rule", code="ROUNDING_RULE_PENDING_CONFIRMATION",
        message=f"取整规则 RSP-RND-001 待确认；本次计算显式采用 {snapshot.rounding_mode.value}，结果不升级为已确认口径。",
        affected_fields=()))

    # 8.1 轨迹引用到的参数表规则进入 citations
    cited_rules = sorted({
        ref for b in branches for ref in b.rule_refs if ref.startswith("RSP-")
    } | {
        ref.removeprefix("rule.")
        for c in calcs for o in c.operands for ref in (o.ref,) if ref.startswith("rule.RSP-")
    })
    for rule_id in cited_rules:
        param = try_get_param(rule_id)
        if param is not None:
            citations.append(DecompositionCitation(
                id=f"rule.{rule_id}", kind="policy_document", ref=param.source,
                value=rule_id, approval_status=param.confirmation_status))

    # 9. 逐字段核对
    fields, identity_calcs = _build_fields(snapshot, split, deductible, funds)
    calcs.extend(identity_calcs)
    from src.runtime.policy_qa.fee_decomposition.secondary_coverage import decompose_secondary_coverage
    computed_base = (deductible.deductible_paid + funds.big_self_pay
                     if deductible.deductible_paid is not None and funds.big_self_pay is not None else None)
    # 大病可报基数：原单 grzif1 有值时以它为准（690/718 实测：972.40×65%＝632.06 与账面一致）；
    # 原单未维护（0/空，如 688）才用本单分量（起付+大额自付）。
    observed_base = snapshot.observed.grzif1
    use_observed = observed_base is not None and observed_base > 0
    base = observed_base if use_observed else computed_base
    if base is not None:
        if use_observed:
            calcs.append(CalculationRecord(
                calculation_id="calc.secondary.personal_base",
                formula_id="secondary_resident_personal_base_v1", formula_version="v1",
                operands=(CalculationOperand("fact.settlement.grzif1", decimal_to_str(observed_base)),),
                result=decimal_to_str(base), rounding_rule="not_applicable（按原单自付一列）"))
        else:
            assert deductible.deductible_paid is not None and funds.big_self_pay is not None
            calcs.append(CalculationRecord(
                calculation_id="calc.secondary.personal_base",
                formula_id="secondary_resident_personal_base_v1", formula_version="v1",
                operands=(CalculationOperand("calc.deductible.paid", decimal_to_str(deductible.deductible_paid)),
                          CalculationOperand("calc.big_pay.self_pay", decimal_to_str(funds.big_self_pay))),
                result=decimal_to_str(base), rounding_rule="not_applicable"))
    secondary = decompose_secondary_coverage(snapshot, self_pay_1=base,
        proportional_self_pay_2=split.total_proportional_self_pay if split is not None else None,
        total_out_scope=split.total_out_scope if split is not None else None)
    fields = [field for field in fields if field.field_code != "PERSON_PAYABLE"]
    fields.extend(secondary.fields)
    branches.extend(secondary.branches)
    calcs.extend(secondary.calculations)
    uncertainties.extend(secondary.uncertainties)
    citations.extend(secondary.citations)
    recon_status = overall_reconciliation_status(tuple(fields))

    # 10. 总体执行状态
    has_unknown = any(
        b.outcome in (BranchOutcome.UNKNOWN, BranchOutcome.BLOCKED) for b in branches)
    split_complete = split is not None and split.is_complete
    execution = ("complete"
                 if (split_complete and not has_unknown
                     and snapshot.cycle.evidence_status == "confirmed")
                 else "partial")

    cov = coverage_counts(tuple(fields))
    return SettlementDecompositionResult(
        algorithm_version=ALGORITHM_VERSION,
        settlement_ref=snapshot.settlement_ref,
        profile=DecompositionProfile(
            insurance_type=snapshot.insurance_type, medical_category=snapshot.medical_category),
        execution_status=execution,
        fee_items=list(split.explanations) if split is not None else [],
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


def _build_fields(
    snapshot: OutpatientSpecialSnapshot,
    split,
    deductible: _DeductibleOutcome,
    funds: _FundOutcome,
) -> tuple[list[FieldReconciliation], list[CalculationRecord]]:
    """居民门特核对矩阵（issue81 公式组）。

    返回 (字段结果, 恒等式轨迹记录)；轨迹只记录本来已执行的加减，不改核对语义。
    """
    obs = snapshot.observed
    split_complete = split is not None and split.is_complete
    sum_fee = sum((it.fee for it in snapshot.items), Decimal("0"))
    sum_book_in = sum((it.in_scope_fee for it in snapshot.items if it.in_scope_fee is not None),
                      Decimal("0"))
    book_in_complete = all(it.in_scope_fee is not None for it in snapshot.items)
    sum_book_out = sum((it.out_scope_fee for it in snapshot.items if it.out_scope_fee is not None),
                       Decimal("0"))
    book_out_complete = all(it.out_scope_fee is not None for it in snapshot.items)
    sum_book_sp2 = sum(
        (it.full_self_pay_advance for it in snapshot.items
         if it.full_self_pay_advance is not None),
        Decimal("0"))
    book_sp2_complete = all(it.full_self_pay_advance is not None for it in snapshot.items)
    zero = Decimal("0")

    total_in = split.total_in_scope if split is not None and split_complete else None
    total_out = split.total_out_scope if split is not None and split_complete else None
    total_sp2 = split.total_self_pay_2 if split is not None and split_complete else None

    identity_calcs: list[CalculationRecord] = []

    def _identity(field_code, label, observed, operands, *, calculation_id, formula_id):
        """账面恒等字段 + 轨迹记录（解释投影 1.1）；分量缺失时不产生记录。"""
        components = tuple(value for _, value in operands)
        if observed is None or any(v is None for v in components):
            return identity_field(field_code, label, observed, components)
        calc = identity_calculation(
            calculation_id, formula_id,
            tuple(CalculationOperand(ref, decimal_to_str(value))
                  for ref, value in operands if value is not None))
        identity_calcs.append(calc)
        return identity_field(field_code, label, observed, components,
                              calculation_refs=(calc.calculation_id,))

    entries: list[FieldReconciliation] = [
        # 总费用：明细账面 Σzje 汇总核对
        reconcile_field("ZJE", _FIELD_LABELS["ZJE"], CheckType.DETAIL_AGGREGATION,
                        sum_fee, obs.zje, BranchOutcome.TRUE,
                        calculation_refs=("calc.catalog.total_fee",)),
        # 特殊病医保内：独立目录分解 vs 交易账面（快照服务层已拦截 ptybn/ptybw≠0，
        # obs.ybn/ybw 即特殊病口径；普通门诊费用本期不支持，不列核对项）
        reconcile_field("TSBYBN", _FIELD_LABELS["TSBYBN"], CheckType.INDEPENDENT_RECALCULATION,
                        total_in, obs.ybn,
                        BranchOutcome.TRUE if total_in is not None else BranchOutcome.UNKNOWN,
                        calculation_refs=("calc.catalog.total_in_scope",)
                        if split is not None else ()),
        reconcile_field("TSBYBN.detail", _FIELD_LABELS["TSBYBN"] + "（明细账面汇总 Σybnje）",
                        CheckType.DETAIL_AGGREGATION,
                        sum_book_in if book_in_complete else None, obs.ybn,
                        BranchOutcome.TRUE if book_in_complete else BranchOutcome.UNKNOWN),
        reconcile_field("TSBYBW", _FIELD_LABELS["TSBYBW"], CheckType.INDEPENDENT_RECALCULATION,
                        total_out, obs.ybw,
                        BranchOutcome.TRUE if total_out is not None else BranchOutcome.UNKNOWN,
                        calculation_refs=("calc.catalog.total_out_scope",) if split is not None else ()),
        reconcile_field("TSBYBW.detail", _FIELD_LABELS["TSBYBW"] + "（明细账面汇总 Σybwje）",
                        CheckType.DETAIL_AGGREGATION,
                        sum_book_out if book_out_complete else None, obs.ybw,
                        BranchOutcome.TRUE if book_out_complete else BranchOutcome.UNKNOWN),
        # 先行自付：独立逐行计算 vs 交易账面；明细账面汇总另列（issue81：grziftw=Σ明细）
        reconcile_field("GRZIFTW", _FIELD_LABELS["GRZIFTW"], CheckType.INDEPENDENT_RECALCULATION,
                        total_sp2, obs.grziftw,
                        BranchOutcome.TRUE if total_sp2 is not None else BranchOutcome.UNKNOWN,
                        calculation_refs=("calc.catalog.total_self_pay_2",) if split is not None else ()),
        reconcile_field("GRZIFTW.detail", _FIELD_LABELS["GRZIFTW"] + "（明细账面汇总 Σgrziftw）",
                        CheckType.DETAIL_AGGREGATION,
                        sum_book_sp2 if book_sp2_complete else None, obs.grziftw,
                        BranchOutcome.TRUE if book_sp2_complete else BranchOutcome.UNKNOWN),
        # 起付：独立重算 vs 账面
        reconcile_field("YBNQFJE", _FIELD_LABELS["YBNQFJE"], CheckType.INDEPENDENT_RECALCULATION,
                        deductible.deductible_paid, obs.ybnqfje,
                        BranchOutcome.TRUE if deductible.deductible_paid is not None
                        else BranchOutcome.UNKNOWN,
                        calculation_refs=tuple(c.calculation_id for c in deductible.calculations)),
        # 统筹：居民门特不设统筹基金（RSP-POOL-001），属不适用而非“可解释的 0”
        reconcile_field("TCZHF", _FIELD_LABELS["TCZHF"] + "（居民门特不设统筹）",
                        CheckType.INDEPENDENT_RECALCULATION,
                        None, obs.tczhf, BranchOutcome.NOT_APPLICABLE,
                        "RESIDENT_SPECIAL_NO_POOL"),
        reconcile_field("TCZIF", _FIELD_LABELS["TCZIF"] + "（居民门特不设统筹）",
                        CheckType.INDEPENDENT_RECALCULATION,
                        None, obs.tczif, BranchOutcome.NOT_APPLICABLE,
                        "RESIDENT_SPECIAL_NO_POOL"),
        # 基本基金支付/自付：独立重算
        reconcile_field("DEGWYZHF", _FIELD_LABELS["DEGWYZHF"], CheckType.INDEPENDENT_RECALCULATION,
                        funds.big_pay, obs.degwyzhf,
                        BranchOutcome.TRUE if funds.big_pay is not None else BranchOutcome.UNKNOWN,
                        calculation_refs=tuple(c.calculation_id for c in funds.calculations)),
        reconcile_field("DEGWYZIF", _FIELD_LABELS["DEGWYZIF"], CheckType.INDEPENDENT_RECALCULATION,
                        funds.big_self_pay, obs.degwyzif,
                        BranchOutcome.TRUE if funds.big_self_pay is not None
                        else BranchOutcome.UNKNOWN,
                        calculation_refs=("calc.big_pay.self_pay",)),
        # 补充待遇：居民无（账面非零另报冲突）
        reconcile_field("BCZHF", _FIELD_LABELS["BCZHF"] + "（居民不适用）",
                        CheckType.INDEPENDENT_RECALCULATION,
                        None, obs.bczhf, BranchOutcome.NOT_APPLICABLE,
                        "RESIDENT_SUPPLEMENT_NOT_APPLICABLE"),
        reconcile_field("JCZHF", _FIELD_LABELS["JCZHF"] + "（居民不适用）",
                        CheckType.INDEPENDENT_RECALCULATION,
                        None, obs.jczhf, BranchOutcome.NOT_APPLICABLE,
                        "RESIDENT_SUPPLEMENT_NOT_APPLICABLE"),
        reconcile_field("GFYLBCHBX", _FIELD_LABELS["GFYLBCHBX"] + "（居民不适用）",
                        CheckType.INDEPENDENT_RECALCULATION,
                        None, obs.gfylbchbx, BranchOutcome.NOT_APPLICABLE,
                        "RESIDENT_SUPPLEMENT_NOT_APPLICABLE"),
    ]

    # 居民门特恒等式（issue81 公式组，账面观测分量，identity_check）：
    # 个人应付 vs 支付渠道（xjzf+zhzf）；机构支付 vs（总费用−支付渠道）
    # 个人支付自付（一）金额：grzif1 列在已核样本中未维护，查询层未取该列，
    # 无账面核对目标 → observed=None 恒 not_verifiable（不自比自判定 matched）；
    # calculated 保留本单分量合计（起付+大额自付）并按加法留痕，
    # 与定额内核 GRZIF1 同码同义，便于页面统一展示。
    if deductible.deductible_paid is not None and funds.big_self_pay is not None:
        self_pay_1_total = deductible.deductible_paid + funds.big_self_pay
        identity_calcs.append(CalculationRecord(
            calculation_id="calc.self_pay_1.parts",
            formula_id="self_pay_1_components_v1",
            formula_version="v1",
            operands=(
                CalculationOperand("calc.deductible.paid", decimal_to_str(deductible.deductible_paid)),
                CalculationOperand("calc.big_pay.self_pay", decimal_to_str(funds.big_self_pay)),
            ),
            unrounded_result=decimal_to_str(self_pay_1_total),
            rounding_rule="not_applicable（加法，无取整）",
            result=decimal_to_str(self_pay_1_total)))
        entries.append(reconcile_field(
            "GRZIF1", _FIELD_LABELS["GRZIF1"], CheckType.INDEPENDENT_RECALCULATION,
            self_pay_1_total, None, BranchOutcome.TRUE,
            "SELF_PAY_1_BOOK_COLUMN_UNMAINTAINED",
            calculation_refs=("calc.self_pay_1.parts",)))
    else:
        entries.append(reconcile_field(
            "GRZIF1", _FIELD_LABELS["GRZIF1"], CheckType.INDEPENDENT_RECALCULATION,
            None, None, BranchOutcome.UNKNOWN, "SELF_PAY_1_COMPONENTS_MISSING"))
    channel_total = (
        obs.xjzf + obs.zhzf
        if obs.xjzf is not None and obs.zhzf is not None else None)
    entries.append(identity_field(
        "PERSON_PAYABLE", "个人应付（=自付一−补助+特殊病医保外，对照 现金+账户）",
        channel_total,
        (obs.ybnqfje, obs.tczif, obs.degwyzif,
         obs.bczhf.copy_negate() if obs.bczhf is not None else None,
         obs.jczhf.copy_negate() if obs.jczhf is not None else None,
         obs.gfylbchbx.copy_negate() if obs.gfylbchbx is not None else None,
         obs.ybw)))
    agency_observed = (
        obs.zje - channel_total
        if obs.zje is not None and channel_total is not None else None)
    entries.append(_identity(
        "AGENCY_PAY", "机构支付合计（含基本医保、大病保险及救助，对照总费用−个人渠道）",
        agency_observed,
        (("TCZHF", obs.tczhf), ("DEGWYZHF", obs.degwyzhf), ("BCZHF", obs.bczhf),
         ("JCZHF", obs.jczhf), ("GFYLBCHBX", obs.gfylbchbx), ("BIG_ILL_PAY", obs.big_ill_pay),
         ("CIVIL_IN", obs.civil_in), ("RETIRE_OFFICER_PAY", obs.retire_officer_pay)),
        calculation_id="calc.identity.agency_pay", formula_id="identity_agency_pay_v1"))
    # 现金/账户：支付渠道仅观测（688/690 xjzf=0 与个人应付不一致，渠道规则未确认）
    for code in ("XJZF", "ZHZF"):
        value = obs.xjzf if code == "XJZF" else obs.zhzf
        entries.append(reconcile_field(
            code, _FIELD_LABELS[code], CheckType.DETAIL_AGGREGATION,
            None, value, BranchOutcome.UNKNOWN, "PAYMENT_CHANNEL_REPLAY_UNAVAILABLE"))
    return entries, identity_calcs
