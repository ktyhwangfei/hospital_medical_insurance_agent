"""Issue #82：职工门特肾/肝肾抗排异定额链路，实际费用与医院定额分别核算。"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    BranchOutcome, BranchTrace, CalculationOperand, CalculationRecord, CheckType,
    DecompositionUncertainty, FieldReconciliation, OutpatientSpecialSnapshot, decimal_to_str,
)
from src.runtime.policy_qa.fee_decomposition.employee_outpatient_special import (
    _DeductibleOutcome, _FIELD_LABELS, _FundOutcome, _MilitaryOutcome, _PmedOutcome, _RetireOutcome,
    decompose_employee_outpatient_special,
)
from src.runtime.policy_qa.fee_decomposition.params_employee_outpatient_special import select_large_cap, select_pool_cap
from src.runtime.policy_qa.fee_decomposition.reconciliation import (
    identity_calculation, identity_field, reconcile_field,
)
from src.runtime.policy_qa.fee_decomposition.result import CitationModel, SettlementDecompositionResult
from src.runtime.policy_qa.fee_decomposition.snapshot_service_special_mz import _unavailable_result
from src.runtime.policy_qa.fee_decomposition.secondary_coverage import SecondaryCoverageResult
from src.runtime.policy_qa.fee_decomposition.result import CoverageSummary, field_to_model

ALGORITHM_VERSION = "employee_special_fixed_kidney_v1"
ZERO = Decimal("0")
ISSUE_REF = "https://github.com/ktyhwangfei/hospital_medical_insurance_agent/issues/82"


def _blocked(snapshot: OutpatientSpecialSnapshot, code: str, message: str) -> SettlementDecompositionResult:
    result = _unavailable_result(snapshot.djh, code, message)
    obs = snapshot.observed
    observations = {"ZJE": obs.zje, "YBN": obs.ybn, "YBW": obs.ybw, "GRZIFTW": obs.grziftw,
        "YBNQFJE": obs.ybnqfje, "TCZHF": obs.tczhf, "TCZIF": obs.tczif,
        "DEGWYZHF": obs.degwyzhf, "DEGWYZIF": obs.degwyzif, "BCZHF": obs.bczhf,
        "JCZHF": obs.jczhf, "GFYLBCHBX": obs.gfylbchbx, "BIG_ILL_PAY": obs.big_ill_pay,
        "CIVIL_IN": obs.civil_in, "FEEIN_DB_PAY": obs.feein_db_pay, "FEEOUT_DB_PAY": obs.feeout_db_pay,
        "FEEIN_MAF_PAY": obs.feein_maf_pay, "FEEOUT_MAF_PAY": obs.feeout_maf_pay,
        "PERSON_PAYABLE": obs.xjzf + obs.zhzf if obs.xjzf is not None and obs.zhzf is not None else None}
    if snapshot.kidney_fixed_quota is not None:
        observations.update(QUOTA_AMOUNT=snapshot.kidney_fixed_quota.quota_amount,
            GRZIF1=snapshot.kidney_fixed_quota.initial_self_pay_observed, AGENCY_PAY=snapshot.kidney_fixed_quota.agency_pay_observed)
    labels = {**_FIELD_LABELS, "BIG_ILL_PAY": "大病保险支付", "CIVIL_IN": "医疗救助支付",
        "FEEIN_DB_PAY": "大病保险自付一支付", "FEEOUT_DB_PAY": "大病保险自付二支付",
        "FEEIN_MAF_PAY": "医疗救助自付一支付", "FEEOUT_MAF_PAY": "医疗救助自付二支付",
        "PERSON_PAYABLE": "个人应付", "QUOTA_AMOUNT": "医院核定定额",
        "GRZIF1": "原始个人自付一", "AGENCY_PAY": "医院垫付基金合计"}
    fields = [field_to_model(reconcile_field(key, labels[key]+"（范围未确认，仅账面）", CheckType.INDEPENDENT_RECALCULATION,
        None, value, BranchOutcome.UNKNOWN, code)) for key, value in observations.items()]
    return result.model_copy(update={"algorithm_version": ALGORITHM_VERSION,
        "fields": fields, "coverage": CoverageSummary(target_field_count=len(fields), independently_explained_count=0,
            amount_reconciled_count=0, observed_only_count=sum(field.observed_amount is not None for field in fields)),
        "citations": [CitationModel(id="rule.fixed.issue82", kind="issue_note", ref=ISSUE_REF)]})


def decompose_kidney_fixed_quota(snapshot: OutpatientSpecialSnapshot) -> SettlementDecompositionResult:
    """单独入口：资格、用药时段及范围未证明时，不把全部门特费用当定额。"""
    ctx = snapshot.kidney_fixed_quota
    if ctx is None or not {"503", "504"}.intersection(ctx.special_codes) or snapshot.yllb != "12" or snapshot.fund_type != "3":
        return _blocked(snapshot, "UNSUPPORTED_FIXED_PROFILE", "未命中职工门特肾/肝肾移植抗排异范围")
    if snapshot.settle_date < date(2005, 11, 1):
        return _blocked(snapshot, "FIXED_POLICY_NOT_EFFECTIVE", "结算日期早于肾移植定额政策生效日期")
    if snapshot.person.civil_medical_eligible is True and snapshot.settle_date < date(2012, 7, 1):
        return _blocked(snapshot, "FIXED_PUBLIC_POLICY_NOT_EFFECTIVE", "定额公费医疗特殊计算规则自2012年7月生效；更早版本尚未确认")
    if ctx.designated_hospital_flag != "1":
        return _blocked(snapshot, "FIXED_DESIGNATED_HOSPITAL_UNCONFIRMED", "特殊病定点医院标识非1，不能证明定额待遇资格；原始定额支付仅保留观测")
    if "502" in ctx.special_codes:
        return _blocked(snapshot, "FIXED_DIALYSIS_CONCURRENT", "合并肾透析备案，不直接套用抗排异定额；需确认实际适用病种")
    # XL04AD为钙调神经磷酸酶抑制剂分类，当前核实的药品为他克莫司/环孢素。
    # 这是有来源的范围候选，尚无完整定额目录；其他药品/诊疗混合时不能靠金额反推归组。
    if not snapshot.items or any(not item.item_code.startswith("XL04AD") for item in snapshot.items):
        return _blocked(snapshot, "FIXED_MANAGED_SCOPE_UNCONFIRMED", "存在未确认的定额管理项目；需先划分项目付费与定额付费，不能全单降低自付比例")
    start, end = ctx.medication_start, ctx.medication_end
    if start is None or end is None or end < start or start.year != end.year or start.year != snapshot.settle_date.year:
        return _blocked(snapshot, "FIXED_PERIOD_SPLIT_UNCONFIRMED", "给药时间缺失、倒置或跨年度，需按时段取得独立累计后拆分计算")
    cycle_start = ctx.cycle_start  # 备案有效期不等于结算周期，缺周期起点不能回退。
    if cycle_start is None or start < cycle_start or end >= cycle_start + timedelta(days=360):
        return _blocked(snapshot, "FIXED_PERIOD_SPLIT_UNCONFIRMED", "给药期间跨结算周期或周期起点未确认，不能使用单周期累计")
    if any(item.fee_date is None or item.fee_date.year != start.year or item.fee_date < cycle_start
           or item.fee_date >= cycle_start + timedelta(days=360) for item in snapshot.items):
        return _blocked(snapshot, "FIXED_PERIOD_SPLIT_UNCONFIRMED", "费用发生期间与给药年度/周期不一致，需取得分期累计")
    if ctx.quota_amount is not None and (not ctx.quota_amount.is_finite() or ctx.quota_amount < ZERO):
        return _blocked(snapshot, "FIXED_QUOTA_INVALID", "定额金额非法，不取绝对值或默认零")
    result = decompose_employee_outpatient_special(snapshot, _fixed_quota=True)
    citations = [*result.citations,
        CitationModel(id="rule.fixed.issue82", kind="issue_note", ref=ISSUE_REF, approval_status="pending"),
        CitationModel(id="rule.fixed.drug_code", kind="policy_document",
            ref="https://www.nhsa.gov.cn/art/2019/6/27/art_53_1436.html", value="西药类别编码用于候选划分，完整定额管理目录待确认"),
        CitationModel(id="fact.fixed.quota", kind="settlement_fact", ref=f"snapshot:{snapshot.settlement_ref}/tsbybn1",
            value=decimal_to_str(ctx.quota_amount) if ctx.quota_amount is not None else None,
            values=[f"给药日期={start.isoformat()}..{end.isoformat()}", f"给付天数={(end-start).days+1}", "账面定额为条件输入，不反算日标准"])]
    return result.model_copy(update={"algorithm_version": ALGORITHM_VERSION, "citations": citations})


def compute_quota_hospital_funds(snapshot: OutpatientSpecialSnapshot, deductible: _DeductibleOutcome,
                                 patient: _FundOutcome) -> _FundOutcome:
    """医院基金=定额−含起付的原始自付，先统筹后大额；患者基数仍为实际费用。"""
    ctx = snapshot.kidney_fixed_quota
    assert ctx is not None
    components = (deductible.deductible_paid, patient.pool_self_pay, patient.large_self_pay)
    pool_cap, large_cap = select_pool_cap(snapshot.settle_date), select_large_cap(snapshot.settle_date)
    prior_pool, prior_large = snapshot.cycle.prior_annual_pool_fund_payment, snapshot.cycle.prior_annual_large_fund_payment
    reason = None
    if ctx.quota_amount is None or any(value is None for value in components):
        reason = "FIXED_FUND_BASE_UNCONFIRMED"
    elif pool_cap.param is None or pool_cap.param.value is None or large_cap.param is None or large_cap.param.value is None or prior_pool is None or prior_large is None:
        reason = "FIXED_FUND_CAP_UNCONFIRMED"
    else:
        assert deductible.deductible_paid is not None and patient.pool_self_pay is not None and patient.large_self_pay is not None
        personal = deductible.deductible_paid + patient.pool_self_pay + patient.large_self_pay
        available = ctx.quota_amount - personal
        pool = min(max(ZERO, pool_cap.param.value - prior_pool), max(ZERO, available))
        large = available - pool
        if available < ZERO:
            reason = "FIXED_QUOTA_BELOW_SELF_PAY"
        elif prior_large >= large_cap.param.value or prior_large + large > large_cap.param.value:
            reason = "FIXED_LARGE_CAP_SPLIT_UNCONFIRMED"
        # 医院定额跨统筹限额会影响实际自付段分配，未取得分段日期/份额时明确阻断。
        elif pool > ZERO and large > ZERO:
            reason = "FIXED_POOL_CAP_SPLIT_UNCONFIRMED"
        else:
            calc = CalculationRecord("calc.fixed.hospital_fund", "fixed_quota_minus_original_self_pay", "v1",
                operands=(CalculationOperand("fact.fixed.quota", decimal_to_str(ctx.quota_amount)),
                          CalculationOperand("calc.fixed.initial_self", decimal_to_str(personal)),
                          CalculationOperand("fact.cycle.prior_pool", decimal_to_str(prior_pool)),
                          CalculationOperand("fact.cycle.prior_large", decimal_to_str(prior_large))),
                unrounded_result=decimal_to_str(available), result=decimal_to_str(available), rounding_rule="已取整自付金额相减")
            return replace(patient, pool_pay=pool, large_pay=large, branches=(BranchTrace(
                "fixed.hospital_fund", "fixed_quota", BranchOutcome.TRUE, rule_refs=("issue82.6",), calculation_refs=(calc.calculation_id,)),),
                calculations=(calc,), uncertainties=())
    return replace(patient, pool_pay=None, large_pay=None, outcome=BranchOutcome.BLOCKED, reason_code=reason,
        branches=(BranchTrace("fixed.hospital_fund", "fixed_quota", BranchOutcome.BLOCKED, reason_code=reason),), calculations=(),
        uncertainties=(DecompositionUncertainty("u.fixed.fund", reason or "FIXED_FUND_BASE_UNCONFIRMED", "医院定额基金基数或限额拆分尚未确认", ("TCZHF", "DEGWYZHF")),))


def quota_reconciliations(snapshot: OutpatientSpecialSnapshot, deductible: _DeductibleOutcome,
                          patient: _FundOutcome, hospital: _FundOutcome, retire: _RetireOutcome,
                          military: _MilitaryOutcome | None, public: _PmedOutcome | None,
                          secondary: SecondaryCoverageResult) -> tuple[list[FieldReconciliation], list[CalculationRecord], list[DecompositionUncertainty]]:
    """额外核对定额、原始自付与医院垫付；不把账面定额伪装成独立计算。"""
    ctx = snapshot.kidney_fixed_quota
    assert ctx is not None
    original = None
    if deductible.deductible_paid is not None and patient.pool_self_pay is not None and patient.large_self_pay is not None:
        original = deductible.deductible_paid + patient.pool_self_pay + patient.large_self_pay
    calculations = []
    if original is not None:
        assert deductible.deductible_paid is not None and patient.pool_self_pay is not None and patient.large_self_pay is not None
        calculations.append(CalculationRecord("calc.fixed.initial_self", "fixed_actual_self_pay", "v1",
            operands=(CalculationOperand("calc.deductible.paid", decimal_to_str(deductible.deductible_paid)),
                      CalculationOperand("calc.pool.self", decimal_to_str(patient.pool_self_pay)),
                      CalculationOperand("calc.large.self", decimal_to_str(patient.large_self_pay))), result=decimal_to_str(original)))
    fields: list[FieldReconciliation] = [
        reconcile_field("QUOTA_AMOUNT", "医院核定定额（条件输入，日标准待确认）", CheckType.INDEPENDENT_RECALCULATION,
            None, ctx.quota_amount, BranchOutcome.UNKNOWN, "FIXED_DAILY_STANDARD_UNCONFIRMED"),
        reconcile_field("GRZIF1", "定额范围内原始自付一（含起付）", CheckType.INDEPENDENT_RECALCULATION,
            original, ctx.initial_self_pay_observed, calculation_refs=("calc.fixed.initial_self",)),
    ]
    payments = (("TCZHF", hospital.pool_pay), ("DEGWYZHF", hospital.large_pay),
                ("BCZHF", retire.amount), ("JCZHF", military.amount if military else None),
                ("GFYLBCHBX", public.amount if public else None),
                ("BIG_ILL_PAY", secondary.big_ill_pay), ("CIVIL_IN", secondary.civil_in))
    agency = (sum((value for _, value in payments if value is not None), ZERO)
              if all(value is not None for _, value in payments) else None)
    agency_calc = None
    if agency is not None:
        # 医院垫付合计的已执行加总轨迹（各分量为已定金额相加，非账面观测分量）
        agency_calc = identity_calculation("calc.identity.fixed_agency_pay",
            "identity_fixed_agency_pay_v1",
            tuple(CalculationOperand(ref, decimal_to_str(value))
                  for ref, value in payments if value is not None))
        calculations.append(agency_calc)
    fields.append(reconcile_field("AGENCY_PAY", "医院垫付基金合计", CheckType.IDENTITY_CHECK, agency,
        ctx.agency_pay_observed,
        calculation_refs=(agency_calc.calculation_id,) if agency_calc is not None else (),
        uncertainty_refs=("u.fixed.quota",)))
    # 这条恒等核对只证明医院定额的平衡，实际费用的患者支付另有独立PERSON_PAYABLE核对。
    obs = snapshot.observed
    quota_balance_operands = (("AGENCY_PAY", ctx.agency_pay_observed), ("XJZF", obs.xjzf),
        ("ZHZF", obs.zhzf), ("YBW", obs.ybw.copy_negate() if obs.ybw is not None else None))
    quota_components = tuple(value for _, value in quota_balance_operands)
    quota_calc = None
    if ctx.quota_amount is not None and not any(v is None for v in quota_components):
        quota_calc = identity_calculation("calc.identity.quota_balance",
            "identity_quota_balance_v1",
            tuple(CalculationOperand(ref, decimal_to_str(value))
                  for ref, value in quota_balance_operands if value is not None))
        calculations.append(quota_calc)
    fields.append(identity_field("QUOTA.balance", "医院定额（账面基金+个人支付−医保外费用）",
        ctx.quota_amount, quota_components,
        calculation_refs=(quota_calc.calculation_id,) if quota_calc is not None else ()))
    uncertainties = [DecompositionUncertainty("u.fixed.quota", "FIXED_DAILY_STANDARD_UNCONFIRMED",
        "手术日期、日定额版本及完整管理目录未确认；医院基金按源定额条件核对，不宣称独立核定定额", ("QUOTA_AMOUNT", "TCZHF", "DEGWYZHF", "AGENCY_PAY"))]
    return fields, calculations, uncertainties
