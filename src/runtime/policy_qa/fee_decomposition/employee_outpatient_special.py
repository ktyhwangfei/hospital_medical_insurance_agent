"""职工门特（门诊特殊病，视同住院）费用分解流程编排（Issue #78 第二流程）。

组合选择：仅 ``employee + outpatient_special``；其他组合明确返回尚不支持，不套用门特公式。

与门诊流程的关键差异：
- 明细 ybnje/ybwje 已是医保内外划分结果（ESP-CAT-001 标识字段待确认，本期不做目录
  逐项独立分解），医保内/外核对为 detail_aggregation（勾稽级，非因果级）；
- 结算周期状态（第几周期、周期内已交起付、年度统筹/大额基金累计）院端不可完整重建，
  由 SpecialCycleContext.evidence_status 三态驱动：
  confirmed → 独立重算；assumed → 可算但全部下游字段勾稽级 + ACCUMULATION_ASSUMED；
  unknown → 起付及统筹/大额字段 not_verifiable + MISSING_CYCLE_CONTEXT；
- allow_observed_deductible=True（评估口径开关，默认 False）且周期上下文非 confirmed 时，
  F 取账面 ybnqfje 作为**条件输入**继续算统筹/大额/退休补助
  （deductible.source=observed_book，勾稽级；是「用账面起付验证比例计算」，
  不违反禁止反推——不同字段）；
- 军残（ESP-DVET）/公疗（ESP-PMED）资格字段未映射 → 一律 observed_only；
  账面 jczhf/gfylbchbx 非零时追加「账面有非零支付但资格未知」uncertainty；
- 取整规则 ESP-RND-001 待确认：取整模式显式传入并如实标注。

统筹分段坐标：段边界（1万/3万/4万）为结算周期内医保内费用累计绝对坐标（含起付段）。
本笔费用坐标下界 C0 = max(D - F, 0)（D 已知时与已交起付一致；D 未知取 0），
属下界假定，记录在计算记录与不确定性中，不升级为已确认口径。
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
    PersonKind,
    apply_rounding,
    decimal_to_str,
)
from src.runtime.policy_qa.fee_decomposition.employee_outpatient import (
    EMPLOYED_PERSON_TYPE_CODES,
    RETIRED_PERSON_TYPE_CODES,
)
from src.runtime.policy_qa.fee_decomposition.params_employee_outpatient_special import (
    select_large_cap,
    select_large_fund_rate,
    select_military_param,
    select_pool_cap,
    select_public_medical_param,
    select_retire_supplement_rates,
    select_retired_factor,
    select_segment_rates,
    try_get_param,
)
from src.runtime.policy_qa.fee_decomposition.reconciliation import (
    coverage_counts,
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

ALGORITHM_VERSION = "employee_outpatient_special_v1"

_MODULE_ID = "employee_outpatient_special"

#: 门特（住院口径）机构等级映射：H_LEVEL 01-05 三级 / 06-09 二级 / 10-13 一级及家庭病床；
#: 其他/空 → 未知（14 在社区门诊口径使用，门特住院分段无社区档，一律未知 fail-closed）
_LEVEL3_CODES = frozenset({"01", "02", "03", "04", "05"})
_LEVEL2_CODES = frozenset({"06", "07", "08", "09"})
_LEVEL1_CODES = frozenset({"10", "11", "12", "13"})

_FIELD_LABELS = {
    "ZJE": "总费用",
    "YBN": "医保内费用",
    "YBW": "医保外费用",
    "GRZIFTW": "先行自付（明细汇总）",
    "YBNQFJE": "本次起付金额",
    "TCZHF": "统筹基金支付",
    "TCZIF": "统筹自付",
    "DEGWYZHF": "大额互助支付",
    "DEGWYZIF": "大额自付",
    "BCZHF": "退休补助",
    "JCZHF": "军残补助",
    "GFYLBCHBX": "公疗补助",
    "XJZF": "现金支付",
    "ZHZF": "账户支付",
}

#: 补充待遇字段集合（供资格未知 uncertainty 引用）
_SUPPLEMENT_FIELDS = ("JCZHF", "GFYLBCHBX")


def _classify_person(cblb: str | None) -> tuple[PersonKind, BranchTrace]:
    """人员身份分类：cblb 候选码（ESP-CODE-003，与门诊 S1 候选集合一致）；未知不默认在职。"""
    if cblb in EMPLOYED_PERSON_TYPE_CODES:
        kind, outcome = PersonKind.EMPLOYED, BranchOutcome.TRUE
    elif cblb in RETIRED_PERSON_TYPE_CODES:
        kind, outcome = PersonKind.RETIRED, BranchOutcome.TRUE
    else:
        kind, outcome = PersonKind.UNKNOWN, BranchOutcome.UNKNOWN
    return kind, BranchTrace(
        step_id="person.classify", module_id="person_classification", scope_ref="settlement",
        condition=BranchCondition("cblb", "人员类别代码属于在职/退休候选集合", "in",
                                  cblb, "ESP-CODE-003 候选代码集"),
        outcome=outcome, reason_code=None if outcome == BranchOutcome.TRUE else "PERSON_TYPE_UNKNOWN",
        input_refs=("fact.registration.cblb",),
        rule_refs=("ESP-CODE-003",))


def _classify_institution(h_level: str | None) -> tuple[str | None, BranchTrace]:
    """机构等级分类（门特住院口径）：01-05 三级 / 06-09 二级 / 10-13 一级；其他/空未知。"""
    level: str | None = None
    outcome = BranchOutcome.UNKNOWN
    reason: str | None = "H_LEVEL_UNKNOWN"
    if h_level is not None:
        code = h_level.strip().zfill(2) if h_level.strip().isdigit() else h_level.strip()
        if code in _LEVEL3_CODES:
            level, outcome, reason = "3", BranchOutcome.TRUE, None
        elif code in _LEVEL2_CODES:
            level, outcome, reason = "2", BranchOutcome.TRUE, None
        elif code in _LEVEL1_CODES:
            level, outcome, reason = "1", BranchOutcome.TRUE, None
    return level, BranchTrace(
        step_id="institution.classify", module_id="person_classification", scope_ref="settlement",
        condition=BranchCondition("h_level", "机构等级（01-05 三级/06-09 二级/10-13 一级）", "in",
                                  h_level, "门特住院口径 H_LEVEL 映射"),
        outcome=outcome, reason_code=reason,
        input_refs=("fact.institution.h_level",),
        rule_refs=("rule.h_level_codes.issue78_special",))


# ── 明细汇总核对 ──────────────────────────────────────────────


@dataclass(frozen=True)
class _DetailSums:
    """明细账面汇总：任一必备列为 None 即不完整（未知不是零，不按零补齐）。"""

    total_fee: Decimal
    total_in_scope: Decimal | None
    total_out_scope: Decimal | None
    total_advance: Decimal | None
    fee_dates: tuple


def _sum_details(snapshot: OutpatientSpecialSnapshot) -> _DetailSums:
    items = snapshot.items
    total_fee = sum((it.fee for it in items), Decimal("0"))

    def _opt_sum(values) -> Decimal | None:
        vals = list(values)
        if any(v is None for v in vals):
            return None
        return sum(vals, Decimal("0"))  # type: ignore[arg-type]

    return _DetailSums(
        total_fee=total_fee,
        total_in_scope=_opt_sum(it.in_scope_fee for it in items),
        total_out_scope=_opt_sum(it.out_scope_fee for it in items),
        total_advance=_opt_sum(it.full_self_pay_advance for it in items),
        fee_dates=tuple(it.fee_date for it in items),
    )


# ── 起付（按周期上下文三态） ──────────────────────────────────


@dataclass(frozen=True)
class _DeductibleOutcome:
    deductible_paid: Decimal | None  # F：本次起付承担
    copay_base: Decimal | None  # B = E - F
    deductible_standard: Decimal | None  # D（observed_book 路径为 None）
    source: str  # recomputed / assumed / observed_book / unavailable
    outcome: BranchOutcome
    reason_code: str | None = None
    branches: tuple[BranchTrace, ...] = ()
    calculations: tuple[CalculationRecord, ...] = ()
    uncertainties: tuple[DecompositionUncertainty, ...] = ()


def _decompose_deductible(
    snapshot: OutpatientSpecialSnapshot, in_scope: Decimal | None
) -> _DeductibleOutcome:
    ctx = snapshot.cycle
    branches: list[BranchTrace] = []
    calcs: list[CalculationRecord] = []
    uncertainties: list[DecompositionUncertainty] = []

    if in_scope is None:
        branches.append(BranchTrace(
            step_id="deductible.base_available", module_id="deductible", scope_ref="settlement",
            condition=BranchCondition("eligible_base", "医保内基数 E 可用性", "not_null", None, "E"),
            outcome=BranchOutcome.BLOCKED, reason_code="UPSTREAM_BASE_MISSING",
            input_refs=("calc.detail.total_in_scope",)))
        uncertainties.append(DecompositionUncertainty(
            id="u.deductible.base", code="UPSTREAM_BASE_MISSING",
            message="明细医保内汇总不完整，起付线分解阻断。",
            affected_fields=("YBNQFJE", "TCZHF", "TCZIF", "DEGWYZHF", "DEGWYZIF", "BCZHF")))
        return _DeductibleOutcome(None, None, None, "unavailable", BranchOutcome.BLOCKED,
                                  "UPSTREAM_BASE_MISSING", tuple(branches), (), tuple(uncertainties))

    status = ctx.evidence_status
    branches.append(BranchTrace(
        step_id="deductible.cycle_context", module_id="deductible", scope_ref="settlement",
        condition=BranchCondition("cycle_evidence", "结算周期/年度累计证据状态", "eq",
                                  status, "confirmed/assumed/unknown"),
        outcome=(BranchOutcome.TRUE if status == "confirmed"
                 else BranchOutcome.UNKNOWN if status == "unknown"
                 else BranchOutcome.UNKNOWN),
        reason_code=None if status == "confirmed" else (
            "MISSING_CYCLE_CONTEXT" if status == "unknown" else "ACCUMULATION_ASSUMED"),
        input_refs=("fact.cycle_context",),
        rule_refs=("ESP-CYC-003", "ESP-DED-001", "ESP-DED-002")))

    if status == "confirmed":
        if ctx.deductible_standard is None or ctx.prior_cycle_deductible_paid is None:
            branches.append(BranchTrace(
                step_id="deductible.split", module_id="deductible", scope_ref="settlement",
                condition=BranchCondition("deductible_inputs", "confirmed 上下文含起付标准与已交起付",
                                          "not_null", None, "D/A"),
                outcome=BranchOutcome.BLOCKED, reason_code="CONFIRMED_CONTEXT_INCOMPLETE"))
            uncertainties.append(DecompositionUncertainty(
                id="u.deductible.context_incomplete", code="CONFIRMED_CONTEXT_INCOMPLETE",
                message="周期上下文标记 confirmed 但缺起付标准或已交起付，不能独立重算。",
                affected_fields=("YBNQFJE",)))
            return _DeductibleOutcome(None, None, None, "unavailable", BranchOutcome.BLOCKED,
                                      "CONFIRMED_CONTEXT_INCOMPLETE",
                                      tuple(branches), (), tuple(uncertainties))
        paid = _split_deductible(in_scope, ctx.deductible_standard,
                                 ctx.prior_cycle_deductible_paid, calcs)
        return _DeductibleOutcome(paid, in_scope - paid, ctx.deductible_standard, "recomputed",
                                  BranchOutcome.TRUE, None,
                                  tuple(branches) + (_deductible_split_branch(paid, in_scope,
                                     ctx.deductible_standard, ctx.prior_cycle_deductible_paid),),
                                  tuple(calcs), ())

    if status == "assumed":
        # 评估口径：假定值可算，但全部下游字段仅勾稽级
        uncertainties.append(DecompositionUncertainty(
            id="u.cycle.assumed", code="ACCUMULATION_ASSUMED",
            message="结算周期/年度累计为评估口径假定值"
                    + (f"（{ctx.evidence_note}）" if ctx.evidence_note else "")
                    + "；起付与统筹/大额分段可计算但不升级为因果级解释。",
            affected_fields=("YBNQFJE", "TCZHF", "TCZIF", "DEGWYZHF", "DEGWYZIF", "BCZHF")))
        if ctx.deductible_standard is None:
            branches.append(BranchTrace(
                step_id="deductible.split", module_id="deductible", scope_ref="settlement",
                condition=BranchCondition("deductible_inputs", "assumed 上下文含起付标准", "not_null",
                                          None, "D"),
                outcome=BranchOutcome.BLOCKED, reason_code="CONFIRMED_CONTEXT_INCOMPLETE"))
            uncertainties.append(DecompositionUncertainty(
                id="u.deductible.context_incomplete", code="CONFIRMED_CONTEXT_INCOMPLETE",
                message="assumed 上下文缺起付标准，不能计算。",
                affected_fields=("YBNQFJE",)))
            return _DeductibleOutcome(None, None, None, "unavailable", BranchOutcome.BLOCKED,
                                      "CONFIRMED_CONTEXT_INCOMPLETE",
                                      tuple(branches), (), tuple(uncertainties))
        prior = ctx.prior_cycle_deductible_paid or Decimal("0")
        paid = _split_deductible(in_scope, ctx.deductible_standard, prior, calcs)
        return _DeductibleOutcome(paid, in_scope - paid, ctx.deductible_standard, "assumed",
                                  BranchOutcome.TRUE, None,
                                  tuple(branches) + (_deductible_split_branch(paid, in_scope,
                                     ctx.deductible_standard, prior),),
                                  tuple(calcs), tuple(uncertainties))

    # unknown：仅评估口径开关允许账面起付作为条件输入
    if snapshot.allow_observed_deductible and snapshot.observed.ybnqfje is not None:
        paid = snapshot.observed.ybnqfje
        branches.append(BranchTrace(
            step_id="deductible.split", module_id="deductible", scope_ref="settlement",
            condition=BranchCondition("deductible_source", "起付来源", "eq",
                                      "observed_book", "recomputed"),
            outcome=BranchOutcome.TRUE, reason_code="OBSERVED_DEDUCTIBLE_AS_INPUT",
            input_refs=("fact.settlement.ybnqfje",),
            rule_refs=("ESP-DED-001", "ESP-DED-002")))
        calcs.append(CalculationRecord(
            calculation_id="calc.deductible.observed", formula_id="observed_deductible_passthrough_v1",
            formula_version="v1",
            operands=(CalculationOperand("fact.settlement.ybnqfje", decimal_to_str(paid)),),
            unrounded_result=decimal_to_str(paid),
            rounding_rule="not_applicable（账面条件输入，无计算）",
            result=decimal_to_str(paid)))
        uncertainties.append(DecompositionUncertainty(
            id="u.deductible.observed_book", code="OBSERVED_DEDUCTIBLE_AS_INPUT",
            message="周期上下文证据不足；评估口径取账面本次起付金额（ybnqfje="
                    + decimal_to_str(paid)
                    + "）作为条件输入继续计算统筹/大额/退休补助，属勾稽级验证，不构成起付的独立因果解释。",
            affected_fields=("YBNQFJE", "TCZHF", "TCZIF", "DEGWYZHF", "DEGWYZIF", "BCZHF")))
        return _DeductibleOutcome(paid, in_scope - paid, None, "observed_book",
                                  BranchOutcome.TRUE, "OBSERVED_DEDUCTIBLE_AS_INPUT",
                                  tuple(branches), tuple(calcs), tuple(uncertainties))

    branches.append(BranchTrace(
        step_id="deductible.split", module_id="deductible", scope_ref="settlement",
        condition=BranchCondition("deductible_source", "起付来源", "eq", None, "recomputed"),
        outcome=BranchOutcome.UNKNOWN, reason_code="MISSING_CYCLE_CONTEXT"))
    uncertainties.append(DecompositionUncertainty(
        id="u.cycle.unknown", code="MISSING_CYCLE_CONTEXT",
        message="结算周期状态（第几周期、周期内已交起付、年度基金累计）在院端数据抽取中不可完整重建"
                + (f"（{ctx.evidence_note}）" if ctx.evidence_note else "")
                + "；起付及统筹/大额字段不可独立计算。",
        affected_fields=("YBNQFJE", "TCZHF", "TCZIF", "DEGWYZHF", "DEGWYZIF", "BCZHF")))
    return _DeductibleOutcome(None, None, None, "unavailable", BranchOutcome.UNKNOWN,
                              "MISSING_CYCLE_CONTEXT", tuple(branches), (), tuple(uncertainties))


def _split_deductible(
    in_scope: Decimal, standard: Decimal, prior_paid: Decimal,
    calcs: list[CalculationRecord],
) -> Decimal:
    """F = min(E, max(D - A, 0))（起付不承担取整：输入均为账面精度金额）。"""
    paid = min(in_scope, max(standard - prior_paid, Decimal("0")))
    calcs.append(CalculationRecord(
        calculation_id="calc.deductible.split", formula_id="special_deductible_split_v1",
        formula_version="v1",
        operands=(
            CalculationOperand("calc.detail.total_in_scope", decimal_to_str(in_scope)),
            CalculationOperand("fact.cycle.prior_deductible_paid", decimal_to_str(prior_paid)),
            CalculationOperand("fact.cycle.deductible_standard", decimal_to_str(standard)),
        ),
        unrounded_result=decimal_to_str(paid),
        rounding_rule="not_applicable（min/max 运算，无取整）",
        result=decimal_to_str(paid)))
    return paid


def _deductible_split_branch(
    paid: Decimal, in_scope: Decimal, standard: Decimal, prior_paid: Decimal
) -> BranchTrace:
    return BranchTrace(
        step_id="deductible.split", module_id="deductible", scope_ref="settlement",
        condition=BranchCondition("deductible_split", "本次起付承担 F=min(E,max(D-A,0))",
                                  "formula", decimal_to_str(paid),
                                  f"E={decimal_to_str(in_scope)},A={decimal_to_str(prior_paid)},D={decimal_to_str(standard)}"),
        outcome=BranchOutcome.TRUE,
        rule_refs=("ESP-DED-001", "ESP-DED-002"),
        input_refs=("calc.detail.total_in_scope", "fact.cycle_context"),
        calculation_refs=("calc.deductible.split",))


# ── 统筹分段 + 封顶 + 大额 ────────────────────────────────────


@dataclass(frozen=True)
class _FundOutcome:
    pool_base: Decimal | None  # 进入统筹段金额 B_pool
    pool_pay: Decimal | None  # TCZHF 统筹基金支付
    pool_self_pay: Decimal | None  # TCZIF 统筹自付
    large_base: Decimal | None  # 进入大额互助段金额 B_large
    large_pay: Decimal | None  # DEGWYZHF 大额互助支付
    large_self_pay: Decimal | None  # DEGWYZIF 大额自付
    outcome: BranchOutcome
    reason_code: str | None = None
    branches: tuple[BranchTrace, ...] = ()
    calculations: tuple[CalculationRecord, ...] = ()
    uncertainties: tuple[DecompositionUncertainty, ...] = ()


def _blocked_fund(reason: str, branches: tuple[BranchTrace, ...],
                  uncertainties: tuple[DecompositionUncertainty, ...]) -> _FundOutcome:
    return _FundOutcome(None, None, None, None, None, None, BranchOutcome.BLOCKED, reason,
                        branches, (), uncertainties)


def _compute_funds(
    snapshot: OutpatientSpecialSnapshot,
    person_kind: PersonKind,
    institution_level: str | None,
    deductible: _DeductibleOutcome,
) -> _FundOutcome:
    """统筹分段支付 + 统筹封顶 + 大额互助（跨段用交集公式）。"""
    branches: list[BranchTrace] = []
    calcs: list[CalculationRecord] = []
    uncertainties: list[DecompositionUncertainty] = []
    settle_date = snapshot.settle_date
    rounding = snapshot.rounding_mode

    copay_base = deductible.copay_base
    if copay_base is None:
        branches.append(BranchTrace(
            step_id="pool.base_available", module_id="pool_fund", scope_ref="settlement",
            condition=BranchCondition("copay_base", "共付段基数 B 可用性", "not_null", None, "B"),
            outcome=BranchOutcome.BLOCKED, reason_code="UPSTREAM_BASE_MISSING",
            input_refs=("calc.deductible.split",)))
        return _blocked_fund("UPSTREAM_BASE_MISSING", tuple(branches), ())

    # 分段比例选择（机构等级 + 结算日期）
    seg_sel = select_segment_rates(institution_level, settle_date)
    branches.append(BranchTrace(
        step_id="pool.segment_select", module_id="pool_fund", scope_ref="settlement",
        condition=BranchCondition("segment_rates", "统筹分段比例选择", "select",
                                  f"level={institution_level}@{settle_date.isoformat()}",
                                  "ESP-RATE-101..112"),
        outcome=seg_sel.outcome, reason_code=seg_sel.reason_code,
        input_refs=("fact.institution.h_level",),
        rule_refs=("ESP-RATE-101", "ESP-RATE-104", "ESP-RATE-105", "ESP-RATE-108",
                   "ESP-RATE-109", "ESP-RATE-112")))
    if seg_sel.outcome != BranchOutcome.TRUE:
        uncertainties.append(DecompositionUncertainty(
            id="u.pool.segment_rates", code=seg_sel.reason_code or "PARAM_VERSION_NOT_FOUND",
            message="适用统筹分段比例不能确定，不采用默认比例。",
            affected_fields=("TCZHF", "TCZIF")))
        return _blocked_fund(seg_sel.reason_code or "PARAM_VERSION_NOT_FOUND",
                             tuple(branches), tuple(uncertainties))

    # 退休自付 = 在职 × 60%（ESP-RATE-113）
    factor = Decimal("1")
    factor_rule: str | None = None
    if person_kind == PersonKind.RETIRED:
        factor_sel = select_retired_factor(settle_date)
        branches.append(BranchTrace(
            step_id="pool.retired_factor", module_id="pool_fund", scope_ref="settlement",
            condition=BranchCondition("retired_factor", "退休自付=在职×60%", "select",
                                      settle_date.isoformat(), "ESP-RATE-113"),
            outcome=factor_sel.outcome, reason_code=factor_sel.reason_code,
            rule_refs=("ESP-RATE-113",)))
        if factor_sel.outcome != BranchOutcome.TRUE or factor_sel.param is None \
                or factor_sel.param.ratio is None:
            uncertainties.append(DecompositionUncertainty(
                id="u.pool.retired_factor", code=factor_sel.reason_code or "PARAM_VERSION_NOT_FOUND",
                message="退休自付折算系数不能确定。", affected_fields=("TCZHF", "TCZIF")))
            return _blocked_fund(factor_sel.reason_code or "PARAM_VERSION_NOT_FOUND",
                                 tuple(branches), tuple(uncertainties))
        factor = factor_sel.param.ratio
        factor_rule = "ESP-RATE-113"
    elif person_kind == PersonKind.UNKNOWN:
        branches.append(BranchTrace(
            step_id="pool.retired_factor", module_id="pool_fund", scope_ref="settlement",
            condition=BranchCondition("retired_factor", "人员身份未知", "eq", None, "employed/retired"),
            outcome=BranchOutcome.UNKNOWN, reason_code="PERSON_KIND_UNKNOWN"))
        uncertainties.append(DecompositionUncertainty(
            id="u.pool.person_kind", code="PERSON_KIND_UNKNOWN",
            message="人员身份未知，统筹自付比例档不能确定（未知不默认在职）。",
            affected_fields=("TCZHF", "TCZIF")))
        return _blocked_fund("PERSON_KIND_UNKNOWN", tuple(branches), tuple(uncertainties))

    # 分段绝对坐标：confirmed 且携带周期内交易前医保内累计 P（yb_dyxxtsb 交易后口径−本笔）
    # 时用精确坐标 start=P+F；否则按下界 C0=max(D-F,0)（D 未知取 F=观察起付→C0=0，下界假定）
    paid = deductible.deductible_paid if deductible.deductible_paid is not None else Decimal("0")
    d_floor = deductible.deductible_standard if deductible.deductible_standard is not None else paid
    prior_in_scope = snapshot.cycle.prior_cycle_in_scope_total
    exact_coordinate = (snapshot.cycle.evidence_status == "confirmed"
                        and prior_in_scope is not None)
    c0 = prior_in_scope if exact_coordinate else max(d_floor - paid, Decimal("0"))

    # 坐标守卫（Issue #79 mz 套表评估口径）：坐标未确认且各段自付比例不完全相同时，
    # 唯一比例分配不可证明（与封顶「未跨界可证明才可算」同一原则），不按下界硬算
    if snapshot.segment_coordinate_guard and not exact_coordinate:
        distinct_ratios = {seg.employed_self_pay_ratio * factor for seg in seg_sel.segments}
        if len(distinct_ratios) > 1:
            branches.append(BranchTrace(
                step_id="pool.coordinate_guard", module_id="pool_fund", scope_ref="settlement",
                condition=BranchCondition("segment_coordinate",
                                          "分段坐标未知且各段比例不同，唯一比例分配不可证明",
                                          "provable", "false", "唯一分配可证明"),
                outcome=BranchOutcome.BLOCKED, reason_code="SEGMENT_COORDINATE_UNDERDETERMINED",
                input_refs=("fact.cycle.prior_cycle_in_scope_total",),
                rule_refs=tuple(seg.rule_id for seg in seg_sel.segments)))
            uncertainties.append(DecompositionUncertainty(
                id="u.pool.coordinate", code="SEGMENT_COORDINATE_UNDERDETERMINED",
                message="结算周期内医保内费用累计坐标在院端数据中不可得（跨院/新系统无 dyxxtsb 行），"
                        "本笔可能落入不同比例段，统筹/大额字段不可确定，不按坐标下界硬算。",
                affected_fields=("TCZHF", "TCZIF", "DEGWYZHF", "DEGWYZIF")))
            return _blocked_fund("SEGMENT_COORDINATE_UNDERDETERMINED", tuple(branches),
                                 tuple(uncertainties))
    branches.append(BranchTrace(
        step_id="pool.coordinate", module_id="pool_fund", scope_ref="settlement",
        condition=BranchCondition("segment_coordinate",
                                  "共付段起点坐标（confirmed=精确 P；否则下界 C0）",
                                  "eq", decimal_to_str(c0),
                                  "exact" if exact_coordinate else "lower_bound"),
        outcome=BranchOutcome.TRUE,
        reason_code=None if exact_coordinate else "SEGMENT_COORDINATE_LOWER_BOUND",
        input_refs=("fact.cycle.prior_cycle_in_scope_total",),
        rule_refs=tuple(seg.rule_id for seg in seg_sel.segments)))

    start = c0 + paid  # 共付段起点坐标
    end = start + copay_base

    # 逐段交集：a_i = max(0, min(end, upper) - max(start, lower))
    segment_amounts: list[tuple[str, Decimal, Decimal, str]] = []  # (seg, amount, self_ratio, rule_id)
    for seg in seg_sel.segments:
        lower = seg.lower if seg.lower is not None else d_floor
        upper = seg.upper
        hi = end if upper is None else min(end, upper)
        lo = max(start, lower)
        amount = max(Decimal("0"), hi - lo)
        self_ratio = seg.employed_self_pay_ratio * factor
        if amount > 0:
            segment_amounts.append((seg.segment, amount, self_ratio, seg.rule_id))

    # 逐段取整后求和（逐段/汇总取整层级 ESP-RND-001 待确认，如实标注）
    pool_pay = Decimal("0")
    pool_base = Decimal("0")
    operands: list[CalculationOperand] = [
        CalculationOperand("calc.deductible.copay_base", decimal_to_str(copay_base)),
        CalculationOperand(
            "calc.cycle_position_exact" if exact_coordinate
            else "calc.cycle_position_lower_bound", decimal_to_str(c0)),
    ]
    unrounded_total = Decimal("0")
    for seg_name, amount, self_ratio, rule_id in segment_amounts:
        unrounded = amount * (Decimal("1") - self_ratio)
        pay_i = apply_rounding(unrounded, rounding)
        pool_pay += pay_i
        pool_base += amount
        unrounded_total += unrounded
        operands.append(CalculationOperand(f"rule.{rule_id}", decimal_to_str(amount)))
        operands.append(CalculationOperand(f"rule.{rule_id}.self_ratio", decimal_to_str(self_ratio)))
    if factor_rule is not None:
        operands.append(CalculationOperand(f"rule.{factor_rule}", decimal_to_str(factor)))
    calcs.append(CalculationRecord(
        calculation_id="calc.pool.segmented", formula_id="special_pool_segmented_v1",
        formula_version="v1",
        operands=tuple(operands),
        unrounded_result=decimal_to_str(unrounded_total),
        rounding_rule=f"explicit:{rounding.value}(ESP-RND-001 待确认；逐段取整层级待确认)",
        result=decimal_to_str(pool_pay)))
    branches.append(BranchTrace(
        step_id="pool.settle", module_id="pool_fund", scope_ref="settlement",
        condition=BranchCondition("pool_segmented",
                                  "统筹支付=Σ各段交集×(1-自付比例)（退休自付=在职×60%）",
                                  "formula", decimal_to_str(pool_pay),
                                  f"B={decimal_to_str(copay_base)},C0={decimal_to_str(c0)}"),
        outcome=BranchOutcome.TRUE,
        rule_refs=tuple(r for _, _, _, r in segment_amounts)
        + (("ESP-RATE-113",) if factor_rule else ()),
        calculation_refs=("calc.pool.segmented",)))

    # 统筹封顶（基金支付口径）：prior 未知时按 prior=0 下界判断，未跨界可证明才可算
    cap_sel = select_pool_cap(settle_date)
    branches.append(BranchTrace(
        step_id="pool.cap_select", module_id="pool_fund", scope_ref="settlement",
        condition=BranchCondition("pool_cap", "统筹基金年度封顶版本选择", "select",
                                  settle_date.isoformat(), "ESP-CAP-001/002/003"),
        outcome=cap_sel.outcome, reason_code=cap_sel.reason_code,
        rule_refs=("ESP-CAP-001", "ESP-CAP-002", "ESP-CAP-003")))
    if cap_sel.outcome != BranchOutcome.TRUE or cap_sel.param is None or cap_sel.param.value is None:
        uncertainties.append(DecompositionUncertainty(
            id="u.pool.cap", code=cap_sel.reason_code or "PARAM_VERSION_NOT_FOUND",
            message="统筹基金年度封顶不能确定。", affected_fields=("TCZHF", "TCZIF")))
        return _blocked_fund(cap_sel.reason_code or "PARAM_VERSION_NOT_FOUND",
                             tuple(branches), tuple(uncertainties))
    pool_cap = cap_sel.param.value

    prior_pool = snapshot.cycle.prior_annual_pool_fund_payment
    large_base = Decimal("0")
    if prior_pool is None:
        if pool_pay <= pool_cap:
            branches.append(BranchTrace(
                step_id="pool.cap_check", module_id="pool_fund", scope_ref="settlement",
                condition=BranchCondition("pool_cap_check",
                                          "prior 未知：按下界 prior=0 计算未超封顶（未跨界可证明）",
                                          "le", decimal_to_str(pool_pay), decimal_to_str(pool_cap)),
                outcome=BranchOutcome.TRUE, reason_code="CAP_CROSSING_PROVABLY_ABSENT",
                input_refs=("fact.cycle.prior_pool_fund_payment",),
                rule_refs=(cap_sel.param.rule_id,)))
        else:
            branches.append(BranchTrace(
                step_id="pool.cap_check", module_id="pool_fund", scope_ref="settlement",
                condition=BranchCondition("pool_cap_check",
                                          "prior 未知且本笔统筹支付超封顶，跨界不可证否",
                                          "le", decimal_to_str(pool_pay), decimal_to_str(pool_cap)),
                outcome=BranchOutcome.BLOCKED, reason_code="POOL_CAP_CROSSING_UNVERIFIABLE",
                rule_refs=(cap_sel.param.rule_id,)))
            uncertainties.append(DecompositionUncertainty(
                id="u.pool.cap_crossing", code="POOL_CAP_CROSSING_UNVERIFIABLE",
                message="缺交易前年度统筹基金累计支付，且本笔统筹支付超封顶，封顶跨界不可证否，统筹/大额划分阻断。",
                affected_fields=("TCZHF", "TCZIF", "DEGWYZHF", "DEGWYZIF")))
            return _blocked_fund("POOL_CAP_CROSSING_UNVERIFIABLE", tuple(branches),
                                 tuple(uncertainties))
    elif prior_pool >= pool_cap:
        # 周期开始时统筹累计已达封顶：全部进入大额（ESP-DED-004 同向）
        branches.append(BranchTrace(
            step_id="pool.cap_check", module_id="pool_fund", scope_ref="settlement",
            condition=BranchCondition("pool_cap_check", "交易前统筹累计已达封顶", "ge",
                                      decimal_to_str(prior_pool), decimal_to_str(pool_cap)),
            outcome=BranchOutcome.FALSE, reason_code="POOL_CAP_REACHED_BEFORE",
            input_refs=("fact.cycle.prior_pool_fund_payment",),
            rule_refs=(cap_sel.param.rule_id, "ESP-DED-004")))
        large_base = copay_base
        pool_base = Decimal("0")
        pool_pay = Decimal("0")
    elif prior_pool + pool_pay <= pool_cap:
        branches.append(BranchTrace(
            step_id="pool.cap_check", module_id="pool_fund", scope_ref="settlement",
            condition=BranchCondition("pool_cap_check", "交易前统筹累计+本笔支付未超封顶", "le",
                                      decimal_to_str(prior_pool + pool_pay), decimal_to_str(pool_cap)),
            outcome=BranchOutcome.TRUE,
            input_refs=("fact.cycle.prior_pool_fund_payment",),
            rule_refs=(cap_sel.param.rule_id,)))
    else:
        branches.append(BranchTrace(
            step_id="pool.cap_check", module_id="pool_fund", scope_ref="settlement",
            condition=BranchCondition("pool_cap_check", "本笔内跨统筹封顶", "le",
                                      decimal_to_str(prior_pool + pool_pay), decimal_to_str(pool_cap)),
            outcome=BranchOutcome.BLOCKED, reason_code="POOL_CAP_CROSSING_SPLIT_UNCONFIRMED",
            rule_refs=(cap_sel.param.rule_id,)))
        uncertainties.append(DecompositionUncertainty(
            id="u.pool.cap_split", code="POOL_CAP_CROSSING_SPLIT_UNCONFIRMED",
            message="本笔费用内跨统筹封顶；基金/费用口径换算未确认，不自行拆分。",
            affected_fields=("TCZHF", "TCZIF", "DEGWYZHF", "DEGWYZIF")))
        return _blocked_fund("POOL_CAP_CROSSING_SPLIT_UNCONFIRMED", tuple(branches),
                             tuple(uncertainties))

    pool_self = pool_base - pool_pay

    # 大额互助：封顶以上部分按在职 85%/退休 80%
    if large_base == 0:
        branches.append(BranchTrace(
            step_id="large.enter", module_id="large_fund", scope_ref="settlement",
            condition=BranchCondition("large_enter", "存在封顶以上费用进入大额互助", "gt",
                                      "0", "0"),
            outcome=BranchOutcome.FALSE, reason_code="BELOW_POOL_CAP",
            rule_refs=("ESP-LGP-002", "ESP-LGP-003")))
        return _FundOutcome(pool_base, pool_pay, pool_self, Decimal("0"), Decimal("0"),
                            Decimal("0"), BranchOutcome.TRUE, None,
                            tuple(branches), tuple(calcs), tuple(uncertainties))

    rate_sel = select_large_fund_rate(person_kind, settle_date)
    branches.append(BranchTrace(
        step_id="large.rate_select", module_id="large_fund", scope_ref="settlement",
        condition=BranchCondition("large_rate", "大额互助支付比例选择", "select",
                                  f"{person_kind.value}@{settle_date.isoformat()}",
                                  "ESP-LGP-001/002/003"),
        outcome=rate_sel.outcome, reason_code=rate_sel.reason_code,
        rule_refs=("ESP-LGP-001", "ESP-LGP-002", "ESP-LGP-003")))
    if rate_sel.outcome != BranchOutcome.TRUE or rate_sel.param is None or rate_sel.param.ratio is None:
        uncertainties.append(DecompositionUncertainty(
            id="u.large.rate", code=rate_sel.reason_code or "PARAM_VERSION_NOT_FOUND",
            message="大额互助支付比例不能确定。", affected_fields=("DEGWYZHF", "DEGWYZIF")))
        return _blocked_fund(rate_sel.reason_code or "PARAM_VERSION_NOT_FOUND",
                             tuple(branches), tuple(uncertainties))
    large_rate = rate_sel.param.ratio

    large_unrounded = large_base * large_rate
    large_pay = apply_rounding(large_unrounded, rounding)

    # 大额封顶（基金支付口径）：同统筹封顶的下界规则
    lcap_sel = select_large_cap(settle_date)
    branches.append(BranchTrace(
        step_id="large.cap_select", module_id="large_fund", scope_ref="settlement",
        condition=BranchCondition("large_cap", "大额互助年度封顶版本选择", "select",
                                  settle_date.isoformat(), "ESP-LCAP-001/002/003"),
        outcome=lcap_sel.outcome, reason_code=lcap_sel.reason_code,
        rule_refs=("ESP-LCAP-001", "ESP-LCAP-002", "ESP-LCAP-003")))
    if lcap_sel.outcome != BranchOutcome.TRUE or lcap_sel.param is None or lcap_sel.param.value is None:
        uncertainties.append(DecompositionUncertainty(
            id="u.large.cap", code=lcap_sel.reason_code or "PARAM_VERSION_NOT_FOUND",
            message="大额互助年度封顶不能确定。", affected_fields=("DEGWYZHF", "DEGWYZIF")))
        return _blocked_fund(lcap_sel.reason_code or "PARAM_VERSION_NOT_FOUND",
                             tuple(branches), tuple(uncertainties))
    large_cap = lcap_sel.param.value
    prior_large = snapshot.cycle.prior_annual_large_fund_payment
    if prior_large is None:
        if large_pay > large_cap:
            uncertainties.append(DecompositionUncertainty(
                id="u.large.cap_crossing", code="LARGE_CAP_CROSSING_UNVERIFIABLE",
                message="缺交易前年度大额基金累计支付，且本笔大额支付超封顶，跨界不可证否。",
                affected_fields=("DEGWYZHF", "DEGWYZIF")))
            return _blocked_fund("LARGE_CAP_CROSSING_UNVERIFIABLE", tuple(branches),
                                 tuple(uncertainties))
    elif prior_large + large_pay > large_cap:
        uncertainties.append(DecompositionUncertainty(
            id="u.large.cap_split", code="LARGE_CAP_CROSSING_SPLIT_UNCONFIRMED",
            message="本笔费用内跨大额封顶；基金/费用口径换算未确认，不自行拆分。",
            affected_fields=("DEGWYZHF", "DEGWYZIF")))
        return _blocked_fund("LARGE_CAP_CROSSING_SPLIT_UNCONFIRMED", tuple(branches),
                             tuple(uncertainties))

    large_self = large_base - large_pay
    calcs.append(CalculationRecord(
        calculation_id="calc.large.settle", formula_id="special_large_fund_v1", formula_version="v1",
        operands=(
            CalculationOperand("calc.large.base", decimal_to_str(large_base)),
            CalculationOperand(f"rule.{rate_sel.param.rule_id}", decimal_to_str(large_rate)),
        ),
        unrounded_result=decimal_to_str(large_unrounded),
        rounding_rule=f"explicit:{rounding.value}(ESP-RND-001 待确认)",
        result=decimal_to_str(large_pay)))
    branches.append(BranchTrace(
        step_id="large.settle", module_id="large_fund", scope_ref="settlement",
        condition=BranchCondition("large_settle", "大额支付=B_large×比例", "formula",
                                  decimal_to_str(large_pay), None),
        outcome=BranchOutcome.TRUE, rule_refs=(rate_sel.param.rule_id,),
        calculation_refs=("calc.large.settle",)))
    return _FundOutcome(pool_base, pool_pay, pool_self, large_base, large_pay, large_self,
                        BranchOutcome.TRUE, None, tuple(branches), tuple(calcs),
                        tuple(uncertainties))


# ── 退休补充保险补助（ESP-RSUP-001..005） ─────────────────────


@dataclass(frozen=True)
class _RetireOutcome:
    amount: Decimal | None
    outcome: BranchOutcome
    reason_code: str | None = None
    pool_part: Decimal | None = None  # 统筹共付段补助部分（军残/公疗剩余自付口径依赖）
    large_part: Decimal | None = None  # 大额共付段补助部分
    branches: tuple[BranchTrace, ...] = ()
    calculations: tuple[CalculationRecord, ...] = ()
    uncertainties: tuple[DecompositionUncertainty, ...] = ()


def _retire_supplement(
    snapshot: OutpatientSpecialSnapshot,
    person_kind: PersonKind,
    pool_self_pay: Decimal | None,
    large_self_pay: Decimal | None,
    fee_dates: tuple,
) -> _RetireOutcome:
    """退休补助：统筹共付段自付×50% + 大额共付段自付×50%（社会化/预提大额段 60%）。

    门特资格时点以费用发生日期为准（ESP-RSUP-005）；退休类别未知时大额段 blocked
    （不默认 50%），统筹段两类同为 50% 可算。
    """
    mid = "retire_supplement"
    branches: list[BranchTrace] = []
    calcs: list[CalculationRecord] = []
    uncertainties: list[DecompositionUncertainty] = []

    if person_kind != PersonKind.RETIRED:
        branches.append(BranchTrace(
            step_id="rsup.eligibility", module_id=mid, scope_ref="settlement",
            condition=BranchCondition("is_retired", "退休身份", "eq", person_kind.value, "retired"),
            outcome=(BranchOutcome.NOT_APPLICABLE if person_kind == PersonKind.EMPLOYED
                     else BranchOutcome.UNKNOWN),
            reason_code="NOT_RETIRED" if person_kind == PersonKind.EMPLOYED else "PERSON_KIND_UNKNOWN",
            input_refs=("fact.registration.cblb",)))
        if person_kind == PersonKind.EMPLOYED:
            return _RetireOutcome(Decimal("0"), BranchOutcome.NOT_APPLICABLE, "NOT_RETIRED",
                                  pool_part=Decimal("0"), large_part=Decimal("0"),
                                  branches=tuple(branches))
        return _RetireOutcome(None, BranchOutcome.UNKNOWN, "PERSON_KIND_UNKNOWN",
                              branches=tuple(branches))

    # 资格时点：门特以费用发生日期为准（ESP-RSUP-005，2006-04-01 起）
    rsup_effective = select_retire_supplement_rates("normal", snapshot.settle_date)
    eff_param = try_get_param("ESP-RSUP-001")
    effective_from = eff_param.effective_date if eff_param is not None else None
    if any(d is None for d in fee_dates):
        branches.append(BranchTrace(
            step_id="rsup.eligible_date", module_id=mid, scope_ref="settlement",
            condition=BranchCondition("fee_dates", "全部明细费用发生日期可用", "not_null", None,
                                      "fsrq"),
            outcome=BranchOutcome.UNKNOWN, reason_code="FEE_DATE_MISSING",
            input_refs=("fact.items.fee_date",), rule_refs=("ESP-RSUP-005",)))
        return _RetireOutcome(None, BranchOutcome.UNKNOWN, "FEE_DATE_MISSING",
                              branches=tuple(branches),
                              uncertainties=(DecompositionUncertainty(
                                  id="u.rsup.fee_date", code="FEE_DATE_MISSING",
                                  message="部分明细缺费用发生日期，退休补助资格时点不能判定。",
                                  affected_fields=("BCZHF",)),))
    if effective_from is not None and any(d < effective_from for d in fee_dates):
        branches.append(BranchTrace(
            step_id="rsup.eligible_date", module_id=mid, scope_ref="settlement",
            condition=BranchCondition("fee_dates", "全部明细费用发生日期不早于 2006-04-01", "ge",
                                      "mixed", "2006-04-01"),
            outcome=BranchOutcome.BLOCKED, reason_code="CROSS_DATE_ALLOCATION_UNCONFIRMED",
            rule_refs=("ESP-RSUP-005",)))
        return _RetireOutcome(None, BranchOutcome.BLOCKED, "CROSS_DATE_ALLOCATION_UNCONFIRMED",
                              branches=tuple(branches),
                              uncertainties=(DecompositionUncertainty(
                                  id="u.rsup.cross_date", code="CROSS_DATE_ALLOCATION_UNCONFIRMED",
                                  message="存在早于退休补充实施日的费用发生日期，跨日费用在各段的分配依据未确认，不按比例摊分。",
                                  affected_fields=("BCZHF",)),))
    branches.append(BranchTrace(
        step_id="rsup.eligible_date", module_id=mid, scope_ref="settlement",
        condition=BranchCondition("fee_dates", "全部明细费用发生日期不早于 2006-04-01", "ge",
                                  "all", "2006-04-01"),
        outcome=BranchOutcome.TRUE, input_refs=("fact.items.fee_date",),
        rule_refs=("ESP-RSUP-005",)))

    if pool_self_pay is None or large_self_pay is None:
        branches.append(BranchTrace(
            step_id="rsup.base", module_id=mid, scope_ref="settlement",
            condition=BranchCondition("supplement_base", "统筹/大额共付段自付可用性", "not_null",
                                      None, "pool_self/large_self"),
            outcome=BranchOutcome.BLOCKED, reason_code="UPSTREAM_BASE_MISSING",
            input_refs=("calc.pool.segmented",)))
        return _RetireOutcome(None, BranchOutcome.BLOCKED, "UPSTREAM_BASE_MISSING",
                              branches=tuple(branches),
                              uncertainties=(DecompositionUncertainty(
                                  id="u.rsup.base", code="UPSTREAM_BASE_MISSING",
                                  message="统筹/大额共付段自付未得出，退休补助阻断。",
                                  affected_fields=("BCZHF",)),))

    # 退休类别：普通 normal / 社会化 prepaid / 未知（字段未映射，不默认 50%）
    category = snapshot.person.retirement_category
    rates = select_retire_supplement_rates(category, snapshot.settle_date)
    branches.append(BranchTrace(
        step_id="rsup.param_select", module_id=mid, scope_ref="settlement",
        condition=BranchCondition("retire_category", "退休类别（普通/社会化）", "select",
                                  category, "ESP-RSUP-001..004"),
        outcome=(BranchOutcome.TRUE if rates.pool.outcome == BranchOutcome.TRUE
                 and rates.large.outcome == BranchOutcome.TRUE else BranchOutcome.UNKNOWN),
        reason_code=rates.large.reason_code,
        rule_refs=("ESP-RSUP-001", "ESP-RSUP-002", "ESP-RSUP-003", "ESP-RSUP-004")))
    if rates.pool.outcome != BranchOutcome.TRUE or rates.pool.param is None \
            or rates.pool.param.ratio is None:
        return _RetireOutcome(None, BranchOutcome.UNKNOWN,
                              rates.pool.reason_code or "PARAM_VERSION_NOT_FOUND",
                              branches=tuple(branches))

    rounding = snapshot.rounding_mode
    pool_ratio = rates.pool.param.ratio
    pool_calc_unrounded = pool_self_pay * pool_ratio
    pool_part = apply_rounding(pool_calc_unrounded, rounding)
    calcs.append(CalculationRecord(
        calculation_id="calc.rsup.pool", formula_id="special_retire_supplement_pool_v1",
        formula_version="v1",
        operands=(
            CalculationOperand("calc.pool.self_pay", decimal_to_str(pool_self_pay)),
            CalculationOperand(f"rule.{rates.pool.param.rule_id}", decimal_to_str(pool_ratio)),
        ),
        unrounded_result=decimal_to_str(pool_calc_unrounded),
        rounding_rule=f"explicit:{rounding.value}(ESP-RND-001 待确认)",
        result=decimal_to_str(pool_part)))

    if large_self_pay > 0:
        if rates.large.outcome != BranchOutcome.TRUE or rates.large.param is None \
                or rates.large.param.ratio is None:
            branches.append(BranchTrace(
                step_id="rsup.large_segment", module_id=mid, scope_ref="settlement",
                condition=BranchCondition("retire_category", "大额段比例需退休类别确定", "select",
                                          category, "ESP-RSUP-002/004"),
                outcome=BranchOutcome.BLOCKED, reason_code="RETIREMENT_CATEGORY_UNKNOWN"))
            uncertainties.append(DecompositionUncertainty(
                id="u.rsup.large_category", code="RETIREMENT_CATEGORY_UNKNOWN",
                message="存在大额共付段自付，但普通/社会化退休类别未知：大额段 50%/60% 不同，"
                        "不默认 50%，退休补助整体不可确定（统筹段部分仍为独立计算值）。",
                affected_fields=("BCZHF",)))
            return _RetireOutcome(None, BranchOutcome.BLOCKED, "RETIREMENT_CATEGORY_UNKNOWN",
                                  branches=tuple(branches), calculations=tuple(calcs),
                                  uncertainties=tuple(uncertainties))
        large_ratio = rates.large.param.ratio
        large_unrounded = large_self_pay * large_ratio
        large_part = apply_rounding(large_unrounded, rounding)
        calcs.append(CalculationRecord(
            calculation_id="calc.rsup.large", formula_id="special_retire_supplement_large_v1",
            formula_version="v1",
            operands=(
                CalculationOperand("calc.large.self_pay", decimal_to_str(large_self_pay)),
                CalculationOperand(f"rule.{rates.large.param.rule_id}", decimal_to_str(large_ratio)),
            ),
            unrounded_result=decimal_to_str(large_unrounded),
            rounding_rule=f"explicit:{rounding.value}(ESP-RND-001 待确认)",
            result=decimal_to_str(large_part)))
    else:
        large_part = Decimal("0")

    amount = pool_part + large_part
    branches.append(BranchTrace(
        step_id="rsup.amount", module_id=mid, scope_ref="settlement",
        condition=BranchCondition("rsup_amount", "R=统筹段自付×50%+大额段自付×比例", "formula",
                                  decimal_to_str(amount), None),
        outcome=BranchOutcome.TRUE,
        rule_refs=(rates.pool.param.rule_id,)
        + ((rates.large.param.rule_id,) if large_self_pay > 0 and rates.large.param else ()),
        calculation_refs=tuple(c.calculation_id for c in calcs)))
    return _RetireOutcome(amount, BranchOutcome.TRUE, None,
                          pool_part=pool_part, large_part=large_part,
                          branches=tuple(branches), calculations=tuple(calcs),
                          uncertainties=tuple(uncertainties))


# ── 军残补助（ESP-DVET-001..005） ────────────────────────────


@dataclass(frozen=True)
class _MilitaryOutcome:
    amount: Decimal | None
    deductible_ratio: Decimal  # 起付段补助比例 a（公疗公式依赖；无资格/未知=0）
    outcome: BranchOutcome
    reason_code: str | None = None
    branches: tuple[BranchTrace, ...] = ()
    calculations: tuple[CalculationRecord, ...] = ()
    uncertainties: tuple[DecompositionUncertainty, ...] = ()


def _military_supplement(
    snapshot: OutpatientSpecialSnapshot,
    person_kind: PersonKind,
    deductible: _DeductibleOutcome,
    funds: _FundOutcome,
    rsup: _RetireOutcome,
) -> _MilitaryOutcome:
    """军残补助：起付×a + 统筹共付段（剩余）自付×a + 大额共付段（剩余）自付×a。

    在职基数为自付原值（ESP-DVET-001/002）；退休基数为扣除退休补助后的剩余自付
    （ESP-DVET-003/004，依赖退休补助独立计算结果，R 未知不得用零代替）。
    资格由 person.military_grade（yb_brdjxx.cjjrdj，Issue #79 候选口径）给出。
    """
    mid = "military_supplement"
    branches: list[BranchTrace] = []
    calcs: list[CalculationRecord] = []
    uncertainties: list[DecompositionUncertainty] = []

    grade = snapshot.person.military_grade
    raw = snapshot.person.military_grade_raw
    eligible = grade in ("1-4", "5-6")
    branches.append(BranchTrace(
        step_id="dvet.eligibility", module_id=mid, scope_ref="settlement",
        condition=BranchCondition("dvet_eligibility", "军残等级（cjjrdj→等级组）", "in",
                                  f"raw={raw},grade={grade}", "1-4/5-6"),
        outcome=(BranchOutcome.TRUE if eligible
                 else BranchOutcome.NOT_APPLICABLE if raw in (None, "", "0")
                 else BranchOutcome.UNKNOWN),
        reason_code=(None if eligible
                     else "NOT_DISABLED_VETERAN" if raw in (None, "", "0")
                     else "MILITARY_GRADE_UNKNOWN"),
        input_refs=("fact.registration.cjjrdj",),
        rule_refs=("ESP-DVET-001", "ESP-DVET-002", "ESP-DVET-003", "ESP-DVET-004",
                   "ESP-DVET-005")))
    if not eligible:
        if raw in (None, "", "0"):
            return _MilitaryOutcome(Decimal("0"), Decimal("0"), BranchOutcome.NOT_APPLICABLE,
                                    "NOT_DISABLED_VETERAN", tuple(branches))
        return _MilitaryOutcome(None, Decimal("0"), BranchOutcome.UNKNOWN,
                                "MILITARY_GRADE_UNKNOWN", tuple(branches))

    # 比例档选择（在职/退休 × 1-4/5-6）
    rate_sel = select_military_param(person_kind, grade, snapshot.settle_date)
    branches.append(BranchTrace(
        step_id="dvet.rate_select", module_id=mid, scope_ref="settlement",
        condition=BranchCondition("dvet_rate", "军残补助比例档选择", "select",
                                  f"{person_kind.value}+{grade}", "ESP-DVET-001..004"),
        outcome=rate_sel.outcome, reason_code=rate_sel.reason_code,
        rule_refs=("ESP-DVET-001", "ESP-DVET-002", "ESP-DVET-003", "ESP-DVET-004")))
    if rate_sel.outcome != BranchOutcome.TRUE or rate_sel.param is None \
            or rate_sel.param.ratio is None:
        uncertainties.append(DecompositionUncertainty(
            id="u.dvet.rate", code=rate_sel.reason_code or "PARAM_VERSION_NOT_FOUND",
            message="军残补助比例档不能确定。", affected_fields=("JCZHF",)))
        return _MilitaryOutcome(None, Decimal("0"), rate_sel.outcome,
                                rate_sel.reason_code or "PARAM_VERSION_NOT_FOUND",
                                tuple(branches), (), tuple(uncertainties))
    ratio = rate_sel.param.ratio

    # 基数：起付 + 统筹/大额共付段（剩余）自付
    if deductible.deductible_paid is None or funds.pool_self_pay is None \
            or funds.large_self_pay is None:
        branches.append(BranchTrace(
            step_id="dvet.base", module_id=mid, scope_ref="settlement",
            condition=BranchCondition("dvet_base", "起付/统筹/大额自付可用性", "not_null",
                                      None, "F/pool_self/large_self"),
            outcome=BranchOutcome.BLOCKED, reason_code="UPSTREAM_BASE_MISSING",
            input_refs=("calc.deductible.split", "calc.pool.segmented")))
        uncertainties.append(DecompositionUncertainty(
            id="u.dvet.base", code="UPSTREAM_BASE_MISSING",
            message="起付或统筹/大额自付未得出，军残补助阻断。", affected_fields=("JCZHF",)))
        return _MilitaryOutcome(None, Decimal("0"), BranchOutcome.BLOCKED,
                                "UPSTREAM_BASE_MISSING", tuple(branches), (),
                                tuple(uncertainties))

    if person_kind == PersonKind.RETIRED:
        if rsup.pool_part is None or rsup.large_part is None:
            branches.append(BranchTrace(
                step_id="dvet.base", module_id=mid, scope_ref="settlement",
                condition=BranchCondition("dvet_base", "退休补助分段部分可用性（剩余自付口径）",
                                          "not_null", None, "rsup.pool_part/large_part"),
                outcome=BranchOutcome.BLOCKED, reason_code="RETIRE_SUPPLEMENT_BASE_MISSING",
                input_refs=("calc.rsup.pool", "calc.rsup.large"),
                rule_refs=("ESP-DVET-003", "ESP-DVET-004")))
            uncertainties.append(DecompositionUncertainty(
                id="u.dvet.rsup_base", code="RETIRE_SUPPLEMENT_BASE_MISSING",
                message="退休补助未独立得出，剩余自付基数不可用零代替，军残补助阻断。",
                affected_fields=("JCZHF",)))
            return _MilitaryOutcome(None, Decimal("0"), BranchOutcome.BLOCKED,
                                    "RETIRE_SUPPLEMENT_BASE_MISSING", tuple(branches), (),
                                    tuple(uncertainties))
        base_pool = funds.pool_self_pay - rsup.pool_part
        base_large = funds.large_self_pay - rsup.large_part
        base_note = "退休：剩余自付=自付-退休补助"
    else:
        base_pool = funds.pool_self_pay
        base_large = funds.large_self_pay
        base_note = "在职：自付原值"
    base_ded = deductible.deductible_paid

    rounding = snapshot.rounding_mode
    ded_unrounded = base_ded * ratio
    ded_part = apply_rounding(ded_unrounded, rounding)
    pool_unrounded = base_pool * ratio
    pool_part = apply_rounding(pool_unrounded, rounding)
    large_unrounded = base_large * ratio
    large_part = apply_rounding(large_unrounded, rounding)
    calcs.append(CalculationRecord(
        calculation_id="calc.dvet.amount", formula_id="special_military_supplement_v1",
        formula_version="v1",
        operands=(
            CalculationOperand("calc.deductible.paid", decimal_to_str(base_ded)),
            CalculationOperand("calc.pool.self_pay_residual", decimal_to_str(base_pool)),
            CalculationOperand("calc.large.self_pay_residual", decimal_to_str(base_large)),
            CalculationOperand(f"rule.{rate_sel.param.rule_id}", decimal_to_str(ratio)),
        ),
        unrounded_result=decimal_to_str(ded_unrounded + pool_unrounded + large_unrounded),
        rounding_rule=f"explicit:{rounding.value}(ESP-RND-001 待确认；起付/统筹/大额三部分分别取整后求和)",
        result=decimal_to_str(ded_part + pool_part + large_part)))
    amount = ded_part + pool_part + large_part
    branches.append(BranchTrace(
        step_id="dvet.amount", module_id=mid, scope_ref="settlement",
        condition=BranchCondition("dvet_amount",
                                  f"军残=Σ(起付/统筹/大额基数)×{decimal_to_str(ratio)}（{base_note}）",
                                  "formula", decimal_to_str(amount), None),
        outcome=BranchOutcome.TRUE, rule_refs=(rate_sel.param.rule_id, "ESP-DVET-005"),
        calculation_refs=("calc.dvet.amount",)))
    return _MilitaryOutcome(amount, ratio, BranchOutcome.TRUE, None,
                            tuple(branches), tuple(calcs), tuple(uncertainties))


# ── 公费医疗补助（ESP-PMED-001..005） ─────────────────────────

#: 公疗目标支付比例（含公疗后基金目标）：参数表 ESP-PMED-001/002 为文本值，
#: 此处按人员身份显式编码（退休 95%/97%，在职 90%/94%），规则引用随计算记录保留
_PMED_BELOW_TARGET = {PersonKind.RETIRED: Decimal("0.95"), PersonKind.EMPLOYED: Decimal("0.90")}
_PMED_ABOVE_TARGET = {PersonKind.RETIRED: Decimal("0.97"), PersonKind.EMPLOYED: Decimal("0.94")}


@dataclass(frozen=True)
class _PmedOutcome:
    amount: Decimal | None
    outcome: BranchOutcome
    reason_code: str | None = None
    branches: tuple[BranchTrace, ...] = ()
    calculations: tuple[CalculationRecord, ...] = ()
    uncertainties: tuple[DecompositionUncertainty, ...] = ()


def _public_medical_supplement(
    snapshot: OutpatientSpecialSnapshot,
    person_kind: PersonKind,
    deductible: _DeductibleOutcome,
    funds: _FundOutcome,
    rsup: _RetireOutcome,
    dvet: _MilitaryOutcome,
) -> _PmedOutcome:
    """公疗补助（一般公疗，ESP-PMED-001/002/004）。

    起付线以下部分 = F×(c−a)；起付线以上部分 = max(0, B×d − tczhf − degwyzhf
    − bczhf − jczhf + F×a)；c/d 为含公疗后基金目标比例（退休 95%/97%，在职 90%/94%），
    a 为军残起付段补助比例。结算顺序：统筹/大额→退休补助→军残→公疗（ESP-PMED-004）。
    资格由 person.civil_medical_eligible（yb_brdjxx.gwydybz，Issue #79 候选口径）给出。
    """
    mid = "public_medical"
    branches: list[BranchTrace] = []
    calcs: list[CalculationRecord] = []
    uncertainties: list[DecompositionUncertainty] = []

    eligible = snapshot.person.civil_medical_eligible
    branches.append(BranchTrace(
        step_id="pmed.eligibility", module_id=mid, scope_ref="settlement",
        condition=BranchCondition("pmed_eligibility", "公疗资格（gwydybz：0=享受/1=不享受）",
                                  "eq", str(eligible), "True"),
        outcome=(BranchOutcome.TRUE if eligible else BranchOutcome.NOT_APPLICABLE),
        reason_code=None if eligible else "NOT_PUBLIC_MEDICAL",
        input_refs=("fact.registration.gwydybz",),
        rule_refs=("ESP-PMED-001", "ESP-PMED-005")))
    if not eligible:
        return _PmedOutcome(Decimal("0"), BranchOutcome.NOT_APPLICABLE,
                            "NOT_PUBLIC_MEDICAL", tuple(branches))

    if person_kind == PersonKind.UNKNOWN:
        branches.append(BranchTrace(
            step_id="pmed.target_ratio", module_id=mid, scope_ref="settlement",
            condition=BranchCondition("pmed_target", "公疗目标比例需人员身份确定", "select",
                                      None, "退休95%/97% 在职90%/94%"),
            outcome=BranchOutcome.UNKNOWN, reason_code="PERSON_KIND_UNKNOWN",
            rule_refs=("ESP-PMED-001", "ESP-PMED-002")))
        return _PmedOutcome(None, BranchOutcome.UNKNOWN, "PERSON_KIND_UNKNOWN", tuple(branches))

    # 版本门控：ESP-PMED-001/002 按结算日期选版本（值为文本，比例显式编码于内核）
    below_sel = select_public_medical_param("below_deductible", snapshot.settle_date)
    above_sel = select_public_medical_param("above_deductible", snapshot.settle_date)
    branches.append(BranchTrace(
        step_id="pmed.target_ratio", module_id=mid, scope_ref="settlement",
        condition=BranchCondition("pmed_target", "公疗目标比例版本选择", "select",
                                  snapshot.settle_date.isoformat(), "ESP-PMED-001/002"),
        outcome=(BranchOutcome.TRUE
                 if below_sel.outcome == BranchOutcome.TRUE
                 and above_sel.outcome == BranchOutcome.TRUE else BranchOutcome.UNKNOWN),
        reason_code=below_sel.reason_code or above_sel.reason_code,
        rule_refs=("ESP-PMED-001", "ESP-PMED-002")))
    if below_sel.outcome != BranchOutcome.TRUE or above_sel.outcome != BranchOutcome.TRUE:
        uncertainties.append(DecompositionUncertainty(
            id="u.pmed.param", code=below_sel.reason_code or above_sel.reason_code
            or "PARAM_VERSION_NOT_FOUND",
            message="公疗目标比例版本不能确定。", affected_fields=("GFYLBCHBX",)))
        return _PmedOutcome(None, BranchOutcome.UNKNOWN,
                            below_sel.reason_code or above_sel.reason_code
                            or "PARAM_VERSION_NOT_FOUND",
                            tuple(branches), (), tuple(uncertainties))

    # 依赖基数：起付 F、共付段基数 B、统筹/大额支付、退休补助、军残补助
    rsup_amount = rsup.amount if rsup.amount is not None else Decimal("0")
    if person_kind == PersonKind.RETIRED and rsup.outcome != BranchOutcome.TRUE:
        rsup_amount = None  # 退休人员退休补助未知不得按零代入
    missing = (deductible.deductible_paid is None or deductible.copay_base is None
               or funds.pool_pay is None or funds.large_pay is None
               or dvet.amount is None or rsup_amount is None)
    if missing:
        branches.append(BranchTrace(
            step_id="pmed.base", module_id=mid, scope_ref="settlement",
            condition=BranchCondition("pmed_base", "起付/共付基数/各基金支付可用性", "not_null",
                                      None, "F/B/tczhf/degwyzhf/bczhf/jczhf"),
            outcome=BranchOutcome.BLOCKED, reason_code="UPSTREAM_BASE_MISSING",
            rule_refs=("ESP-PMED-004",)))
        uncertainties.append(DecompositionUncertainty(
            id="u.pmed.base", code="UPSTREAM_BASE_MISSING",
            message="公疗计算顺序上游（统筹/大额/退休补助/军残）未完整得出，公疗补助阻断。",
            affected_fields=("GFYLBCHBX",)))
        return _PmedOutcome(None, BranchOutcome.BLOCKED, "UPSTREAM_BASE_MISSING",
                            tuple(branches), (), tuple(uncertainties))

    paid = deductible.deductible_paid
    copay_base = deductible.copay_base
    a = dvet.deductible_ratio
    c = _PMED_BELOW_TARGET[person_kind]
    d = _PMED_ABOVE_TARGET[person_kind]
    rounding = snapshot.rounding_mode

    below_unrounded = paid * max(c - a, Decimal("0"))
    below_part = apply_rounding(below_unrounded, rounding)
    above_unrounded = (copay_base * d - funds.pool_pay - funds.large_pay
                       - rsup_amount - dvet.amount + paid * a)
    above_part = apply_rounding(max(above_unrounded, Decimal("0")), rounding)
    calcs.append(CalculationRecord(
        calculation_id="calc.pmed.amount", formula_id="special_public_medical_v1",
        formula_version="v1",
        operands=(
            CalculationOperand("calc.deductible.paid", decimal_to_str(paid)),
            CalculationOperand("calc.deductible.copay_base", decimal_to_str(copay_base)),
            CalculationOperand("calc.pool.pay", decimal_to_str(funds.pool_pay)),
            CalculationOperand("calc.large.pay", decimal_to_str(funds.large_pay)),
            CalculationOperand("calc.rsup.amount", decimal_to_str(rsup_amount)),
            CalculationOperand("calc.dvet.amount", decimal_to_str(dvet.amount)),
            CalculationOperand("rule.ESP-PMED-001.target", decimal_to_str(c)),
            CalculationOperand("rule.ESP-PMED-002.target", decimal_to_str(d)),
            CalculationOperand("rule.dvet.deductible_ratio", decimal_to_str(a)),
        ),
        unrounded_result=decimal_to_str(below_unrounded + above_unrounded),
        rounding_rule=f"explicit:{rounding.value}(ESP-RND-001 待确认；起付线以下/以上两部分分别取整后求和)",
        result=decimal_to_str(below_part + above_part)))
    amount = below_part + above_part
    branches.append(BranchTrace(
        step_id="pmed.amount", module_id=mid, scope_ref="settlement",
        condition=BranchCondition("pmed_amount",
                                  "公疗=F×(c-a)+max(0,B×d-各基金支付-补助+F×a)",
                                  "formula", decimal_to_str(amount),
                                  f"c={decimal_to_str(c)},d={decimal_to_str(d)},a={decimal_to_str(a)}"),
        outcome=BranchOutcome.TRUE,
        rule_refs=("ESP-PMED-001", "ESP-PMED-002", "ESP-PMED-004"),
        calculation_refs=("calc.pmed.amount",)))
    return _PmedOutcome(amount, BranchOutcome.TRUE, None, tuple(branches), tuple(calcs),
                        tuple(uncertainties))


# ── 主流程 ────────────────────────────────────────────────────


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
    """基础证据引用：码值映射（实测待码表确认）与关键事实。"""
    return [
        DecompositionCitation(
            id="rule.ESP-CODE-003", kind="policy_document",
            ref=try_get_param("ESP-CODE-003").source, value="ESP-CODE-003",
            approval_status="实测待码表确认"),
        DecompositionCitation(
            id="rule.h_level_codes.issue78_special", kind="issue_note",
            ref="docs/superpowers/specs/2026-09-28-issue78-城镇职工门特待遇参数.csv",
            value="H_LEVEL 01-05 三级/06-09 二级/10-13 一级（m_institution 实测映射，待数据字典确认）",
            approval_status="pending"),
        DecompositionCitation(
            id="fact.registration.cblb", kind="settlement_fact",
            ref=f"snapshot:{snapshot.settlement_ref}/yb_brdjxx/cblb",
            value=snapshot.person.cblb),
        DecompositionCitation(
            id="fact.institution.h_level", kind="settlement_fact",
            ref=f"snapshot:{snapshot.settlement_ref}/m_institution/H_LEVEL",
            value=snapshot.institution.h_level),
        DecompositionCitation(
            id="fact.settlement.settle_date", kind="settlement_fact",
            ref=f"snapshot:{snapshot.settlement_ref}/yb_zyjyxx/jyrq",
            value=snapshot.settle_date.isoformat()),
        DecompositionCitation(
            id="fact.cycle_context", kind="settlement_fact",
            ref=f"snapshot:{snapshot.settlement_ref}/cycle_context",
            value=snapshot.cycle.evidence_status,
            values=([snapshot.cycle.evidence_note] if snapshot.cycle.evidence_note else [])),
    ]


def decompose_employee_outpatient_special(
    snapshot: OutpatientSpecialSnapshot,
) -> SettlementDecompositionResult:
    """职工门特（门诊特殊病，视同住院）费用分解主流程。"""
    branches: list[BranchTrace] = []
    calcs: list[CalculationRecord] = []
    uncertainties: list[DecompositionUncertainty] = []
    citations = _base_citations(snapshot)

    # 1. 组合选择：仅职工+门特
    supported = (snapshot.insurance_type == "employee"
                 and snapshot.medical_category == "outpatient_special")
    branches.append(BranchTrace(
        step_id="flow.profile_select", module_id=_MODULE_ID, scope_ref="settlement",
        condition=BranchCondition("profile", "险种×医疗类别组合", "eq",
                                  f"{snapshot.insurance_type}+{snapshot.medical_category}",
                                  "employee+outpatient_special"),
        outcome=BranchOutcome.TRUE if supported else BranchOutcome.NOT_APPLICABLE,
        reason_code=None if supported else "UNSUPPORTED_PROFILE",
        rule_refs=("ESP-CODE-001", "ESP-CODE-002")))
    if not supported:
        uncertainties.append(DecompositionUncertainty(
            id="u.flow.unsupported_profile", code="UNSUPPORTED_PROFILE",
            message="本流程仅支持城镇职工×门诊特殊病；其他组合尚不支持，不套用门特公式。",
            affected_fields=()))
        return _empty_result(snapshot, "unavailable", branches, uncertainties, citations)

    # 2. 明细行键重复/负金额检查：数据异常或未支持重算，不静默去重、不取绝对值
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

    # 3. 人员与机构分类
    person_kind, person_branch = _classify_person(snapshot.person.cblb)
    branches.append(person_branch)
    institution_level, inst_branch = _classify_institution(snapshot.institution.h_level)
    branches.append(inst_branch)

    # 4. 明细汇总核对（ybnje/ybwje 已是划分结果，本期不做目录独立重算）
    sums = _sum_details(snapshot)
    calcs.append(CalculationRecord(
        calculation_id="calc.detail.total_in_scope", formula_id="special_detail_sum_v1",
        formula_version="v1",
        operands=(CalculationOperand("fact.items.ybnje",
                                     decimal_to_str(sums.total_in_scope)
                                     if sums.total_in_scope is not None else "incomplete"),),
        unrounded_result=None, rounding_rule="not_applicable（求和，无取整）",
        result=decimal_to_str(sums.total_in_scope) if sums.total_in_scope is not None else None))
    branches.append(BranchTrace(
        step_id="detail.aggregation", module_id="detail_aggregation", scope_ref="settlement",
        condition=BranchCondition("detail_sums", "明细汇总完整性（zje/ybnje/ybwje/grziftw）", "not_null",
                                  f"in_scope={'ok' if sums.total_in_scope is not None else 'incomplete'}",
                                  "全明细必备列非空"),
        outcome=BranchOutcome.TRUE if sums.total_in_scope is not None else BranchOutcome.UNKNOWN,
        reason_code=None if sums.total_in_scope is not None else "DETAIL_INCOMPLETE",
        input_refs=("fact.items.zje", "fact.items.ybnje", "fact.items.ybwje", "fact.items.grziftw"),
        calculation_refs=("calc.detail.total_in_scope",)))
    if sums.total_in_scope is None:
        uncertainties.append(DecompositionUncertainty(
            id="u.detail.incomplete", code="DETAIL_INCOMPLETE",
            message="部分明细缺医保内金额（ybnje），汇总不完整，不得作为完整合计。",
            affected_fields=("YBN", "YBNQFJE", "TCZHF", "TCZIF", "DEGWYZHF", "DEGWYZIF", "BCZHF")))

    # 5. 起付（周期上下文三态 / 评估口径账面条件输入）
    deductible = _decompose_deductible(snapshot, sums.total_in_scope)
    branches.extend(deductible.branches)
    calcs.extend(deductible.calculations)
    uncertainties.extend(deductible.uncertainties)

    # 6. 统筹分段 + 封顶 + 大额互助
    funds = _compute_funds(snapshot, person_kind, institution_level, deductible)
    branches.extend(funds.branches)
    calcs.extend(funds.calculations)
    uncertainties.extend(funds.uncertainties)

    # 7. 退休补充保险补助（ESP-RSUP）
    rsup = _retire_supplement(snapshot, person_kind, funds.pool_self_pay, funds.large_self_pay,
                              sums.fee_dates)
    branches.extend(rsup.branches)
    calcs.extend(rsup.calculations)
    uncertainties.extend(rsup.uncertainties)

    # 8. 军残/公疗：资格字段已映射（Issue #79 mz 套表 cjjrdj/gwydybz 候选口径）→ 独立计算；
    # 未映射（zy 套表流程）→ 保持 observed_only，账面非零追加 uncertainty
    obs = snapshot.observed
    if snapshot.person.military_grade is not None \
            or snapshot.person.military_grade_raw is not None:
        dvet = _military_supplement(snapshot, person_kind, deductible, funds, rsup)
        branches.extend(dvet.branches)
        calcs.extend(dvet.calculations)
        uncertainties.extend(dvet.uncertainties)
    else:
        dvet = None
        branches.append(BranchTrace(
            step_id="dvet.eligibility", module_id="military_supplement", scope_ref="settlement",
            condition=BranchCondition("dvet_eligibility", "军残资格字段", "mapped", None,
                                      "资格/等级/有效期"),
            outcome=BranchOutcome.UNKNOWN, reason_code="MILITARY_ELIGIBILITY_FIELD_UNMAPPED",
            rule_refs=("ESP-DVET-001", "ESP-DVET-002", "ESP-DVET-003", "ESP-DVET-004",
                       "ESP-DVET-005")))
        if obs.jczhf is not None and obs.jczhf != 0:
            uncertainties.append(DecompositionUncertainty(
                id="u.dvet.book_nonzero", code="BOOK_NONZERO_BUT_ELIGIBILITY_UNKNOWN",
                message=f"账面军残补助 jczhf={decimal_to_str(obs.jczhf)} 非零，但军残资格字段未映射，"
                        "不得由金额反推资格；该金额仅作观测值保留。",
                affected_fields=("JCZHF",)))

    if snapshot.person.civil_medical_eligible is not None:
        if dvet is None:
            raise AssertionError("公疗计算依赖军残结果，军残未计算时公疗资格不应已映射")
        pmed = _public_medical_supplement(snapshot, person_kind, deductible, funds, rsup, dvet)
        branches.extend(pmed.branches)
        calcs.extend(pmed.calculations)
        uncertainties.extend(pmed.uncertainties)
    else:
        pmed = None
        branches.append(BranchTrace(
            step_id="pmed.eligibility", module_id="public_medical", scope_ref="settlement",
            condition=BranchCondition("pmed_eligibility", "公疗资格/本人定点字段", "mapped", None,
                                      "资格+本人定点"),
            outcome=BranchOutcome.UNKNOWN, reason_code="PMED_ELIGIBILITY_FIELD_UNMAPPED",
            rule_refs=("ESP-PMED-001", "ESP-PMED-002", "ESP-PMED-003", "ESP-PMED-004",
                       "ESP-PMED-005")))
        if obs.gfylbchbx is not None and obs.gfylbchbx != 0:
            uncertainties.append(DecompositionUncertainty(
                id="u.pmed.book_nonzero", code="BOOK_NONZERO_BUT_ELIGIBILITY_UNKNOWN",
                message=f"账面公疗补助 gfylbchbx={decimal_to_str(obs.gfylbchbx)} 非零，但公疗资格字段未映射，"
                        "不得由金额反推资格；该金额仅作观测值保留。",
                affected_fields=("GFYLBCHBX",)))

    # 9. 取整规则待确认的全局不确定性（ESP-RND-001；模式已显式传入并记录于各计算记录）
    uncertainties.append(DecompositionUncertainty(
        id="u.rounding.rule", code="ROUNDING_RULE_PENDING_CONFIRMATION",
        message=f"取整规则 ESP-RND-001 待确认；本次计算显式采用 {snapshot.rounding_mode.value}，结果不升级为已确认口径。",
        affected_fields=()))

    # 9.1 轨迹引用到的参数表规则进入 citations（带来源确认状态，未确认不升级）
    cited_rules = sorted({
        ref for b in branches for ref in b.rule_refs if ref.startswith("ESP-")
    } | {
        ref.removeprefix("rule.")
        for c in calcs for o in c.operands for ref in (o.ref,) if ref.startswith("rule.ESP-")
    })
    for rule_id in cited_rules:
        param = try_get_param(rule_id)
        if param is not None:
            citations.append(DecompositionCitation(
                id=f"rule.{rule_id}", kind="policy_document", ref=param.source,
                value=rule_id, approval_status=param.confirmation_status))

    # 10. 逐字段核对（含账面恒等式）
    fields, identity_uncertainties = _build_fields(snapshot, sums, deductible, funds, rsup,
                                                   dvet, pmed)
    uncertainties.extend(identity_uncertainties)
    recon_status = overall_reconciliation_status(tuple(fields))

    # 11. 总体执行状态：unknown/blocked 分支、明细不完整、非 confirmed 周期口径 → partial
    has_unknown = any(
        b.outcome in (BranchOutcome.UNKNOWN, BranchOutcome.BLOCKED) for b in branches)
    assumption_caliber = snapshot.cycle.evidence_status != "confirmed"
    execution = ("complete"
                 if (sums.total_in_scope is not None and not has_unknown and not assumption_caliber)
                 else "partial")

    cov = coverage_counts(tuple(fields))
    return SettlementDecompositionResult(
        algorithm_version=ALGORITHM_VERSION,
        settlement_ref=snapshot.settlement_ref,
        profile=DecompositionProfile(
            insurance_type=snapshot.insurance_type, medical_category=snapshot.medical_category),
        execution_status=execution,
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
    sums: _DetailSums,
    deductible: _DeductibleOutcome,
    funds: _FundOutcome,
    rsup: _RetireOutcome,
    dvet: _MilitaryOutcome | None,
    pmed: _PmedOutcome | None,
) -> tuple[list[FieldReconciliation], list[DecompositionUncertainty]]:
    """按核对矩阵生成全部目标字段结果项（含零值与缺失值；观测值仅作核对目标）。"""
    obs = snapshot.observed
    identity_uncertainties: list[DecompositionUncertainty] = []

    # 假设/条件输入口径的 uncertainty 引用（下游字段勾稽级标注）
    caliber_refs: list[str] = []
    if deductible.source == "assumed":
        caliber_refs.append("u.cycle.assumed")
    elif deductible.source == "observed_book":
        caliber_refs.append("u.deductible.observed_book")
    elif snapshot.cycle.evidence_status == "unknown":
        caliber_refs.append("u.cycle.unknown")

    entries: list[FieldReconciliation] = [
        reconcile_field("ZJE", _FIELD_LABELS["ZJE"], CheckType.DETAIL_AGGREGATION,
                        sums.total_fee, obs.zje, BranchOutcome.TRUE),
        reconcile_field("YBN", _FIELD_LABELS["YBN"], CheckType.DETAIL_AGGREGATION,
                        sums.total_in_scope, obs.ybn,
                        BranchOutcome.TRUE if sums.total_in_scope is not None
                        else BranchOutcome.UNKNOWN,
                        calculation_refs=("calc.detail.total_in_scope",)),
        reconcile_field("YBW", _FIELD_LABELS["YBW"], CheckType.DETAIL_AGGREGATION,
                        sums.total_out_scope, obs.ybw,
                        BranchOutcome.TRUE if sums.total_out_scope is not None
                        else BranchOutcome.UNKNOWN),
        reconcile_field("GRZIFTW", _FIELD_LABELS["GRZIFTW"], CheckType.DETAIL_AGGREGATION,
                        sums.total_advance, obs.grziftw,
                        BranchOutcome.TRUE if sums.total_advance is not None
                        else BranchOutcome.UNKNOWN),
        # 起付：observed_book 路径计算值即账面条件输入，显式标注来源
        reconcile_field("YBNQFJE", _FIELD_LABELS["YBNQFJE"], CheckType.INDEPENDENT_RECALCULATION,
                        deductible.deductible_paid, obs.ybnqfje, deductible.outcome,
                        deductible.reason_code,
                        calculation_refs=tuple(c.calculation_id for c in deductible.calculations),
                        uncertainty_refs=tuple(caliber_refs)),
        reconcile_field("TCZHF", _FIELD_LABELS["TCZHF"], CheckType.INDEPENDENT_RECALCULATION,
                        funds.pool_pay, obs.tczhf, funds.outcome, funds.reason_code,
                        calculation_refs=("calc.pool.segmented",),
                        uncertainty_refs=tuple(caliber_refs)),
        reconcile_field("TCZIF", _FIELD_LABELS["TCZIF"], CheckType.INDEPENDENT_RECALCULATION,
                        funds.pool_self_pay, obs.tczif, funds.outcome, funds.reason_code,
                        calculation_refs=("calc.pool.segmented",),
                        uncertainty_refs=tuple(caliber_refs)),
        reconcile_field("DEGWYZHF", _FIELD_LABELS["DEGWYZHF"], CheckType.INDEPENDENT_RECALCULATION,
                        funds.large_pay, obs.degwyzhf, funds.outcome, funds.reason_code,
                        calculation_refs=("calc.large.settle",) if funds.large_base else (),
                        uncertainty_refs=tuple(caliber_refs)),
        reconcile_field("DEGWYZIF", _FIELD_LABELS["DEGWYZIF"], CheckType.INDEPENDENT_RECALCULATION,
                        funds.large_self_pay, obs.degwyzif, funds.outcome, funds.reason_code,
                        calculation_refs=("calc.large.settle",) if funds.large_base else (),
                        uncertainty_refs=tuple(caliber_refs)),
        reconcile_field("BCZHF", _FIELD_LABELS["BCZHF"], CheckType.INDEPENDENT_RECALCULATION,
                        rsup.amount, obs.bczhf, rsup.outcome, rsup.reason_code,
                        calculation_refs=tuple(c.calculation_id for c in rsup.calculations),
                        uncertainty_refs=tuple(caliber_refs)),
    ]

    # 军残/公疗：资格已映射 → 独立计算值核对；未映射 → observed_only（not_verifiable）
    if dvet is not None:
        entries.append(reconcile_field(
            "JCZHF", _FIELD_LABELS["JCZHF"], CheckType.INDEPENDENT_RECALCULATION,
            dvet.amount, obs.jczhf, dvet.outcome, dvet.reason_code,
            calculation_refs=tuple(c.calculation_id for c in dvet.calculations),
            uncertainty_refs=tuple(caliber_refs)))
    else:
        entries.append(reconcile_field(
            "JCZHF", _FIELD_LABELS["JCZHF"], CheckType.INDEPENDENT_RECALCULATION,
            None, obs.jczhf, BranchOutcome.UNKNOWN,
            "MILITARY_ELIGIBILITY_FIELD_UNMAPPED"))
    if pmed is not None:
        entries.append(reconcile_field(
            "GFYLBCHBX", _FIELD_LABELS["GFYLBCHBX"], CheckType.INDEPENDENT_RECALCULATION,
            pmed.amount, obs.gfylbchbx, pmed.outcome, pmed.reason_code,
            calculation_refs=tuple(c.calculation_id for c in pmed.calculations),
            uncertainty_refs=tuple(caliber_refs)))
    else:
        entries.append(reconcile_field(
            "GFYLBCHBX", _FIELD_LABELS["GFYLBCHBX"], CheckType.INDEPENDENT_RECALCULATION,
            None, obs.gfylbchbx, BranchOutcome.UNKNOWN,
            "PMED_ELIGIBILITY_FIELD_UNMAPPED"))

    # 账面恒等式 1：zje = ybn + ybw（只证明账面字段间等式，不证明字段原因）
    entries.append(identity_field("ZJE.identity", _FIELD_LABELS["ZJE"] + "（账面恒等 医保内+医保外）",
                                  obs.zje, (obs.ybn, obs.ybw)))
    # 账面恒等式 2：xjzf + zhzf = zje - tczhf - degwyzhf - bczhf - jczhf - gfylbchbx
    channel_sum = (obs.xjzf + obs.zhzf) if (obs.xjzf is not None and obs.zhzf is not None) else None
    cash_identity = identity_field(
        "XJZF.identity", "现金+账户支付（账面恒等：总费用-各基金支付）", channel_sum,
        (obs.zje,
         -obs.tczhf if obs.tczhf is not None else None,
         -obs.degwyzhf if obs.degwyzhf is not None else None,
         -obs.bczhf if obs.bczhf is not None else None,
         -obs.jczhf if obs.jczhf is not None else None,
         -obs.gfylbchbx if obs.gfylbchbx is not None else None))
    entries.append(cash_identity)
    if cash_identity.check_status.value == "mismatched" and cash_identity.difference is not None:
        identity_uncertainties.append(DecompositionUncertainty(
            id="u.identity.cash_mismatch", code="CASH_IDENTITY_MISMATCH",
            message=f"现金+账户支付与账面基金抵扣恒等式不成立，差额 {cash_identity.difference} 元如实保留；"
                    "疑似存在未入账面的补助渠道（如公疗目标补助，规则未确认），不得凑平。",
            affected_fields=("XJZF", "ZHZF")))
    # 账户/现金：缺少当时扣款规则与支付流水，仅报告账面渠道金额
    for code in ("XJZF", "ZHZF"):
        value = obs.xjzf if code == "XJZF" else obs.zhzf
        entries.append(reconcile_field(
            code, _FIELD_LABELS[code], CheckType.DETAIL_AGGREGATION,
            None, value, BranchOutcome.UNKNOWN, "PAYMENT_CHANNEL_REPLAY_UNAVAILABLE"))
    return entries, identity_uncertainties
