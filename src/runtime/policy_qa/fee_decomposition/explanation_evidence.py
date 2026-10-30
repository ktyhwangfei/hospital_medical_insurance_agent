"""公式输入证据；保留引用身份，读取事实与待遇适用性分别验证。"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.domain.insurance.fee_decomposition import DecompositionSnapshot, OutpatientSpecialSnapshot, SpecialPersonProfile, SpecialFeeLineItem

if TYPE_CHECKING:
    from src.runtime.policy_qa.fee_decomposition.result import SettlementDecompositionResult

EvidenceStatus = Literal["verified", "unverified", "missing", "conflict"]


def input_id(ref: str) -> str:
    """公开编号不携带物理列或患者标识；同一引用始终得到同一编号。"""
    return "input-" + sha256(ref.encode()).hexdigest()[:16]


class FormulaInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_id: str
    name: str
    value: str | None = None
    status: EvidenceStatus = "unverified"
    source: str
    reason: str | None = None
    calculation_ref: str | None = None
    rule_group_ref: str | None = None
    rule_id: str | None = None


class CandidateCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    actual: str | None = None
    expected: str
    outcome: Literal["met", "unmet", "unknown"]
    input_ref: str | None = None


class RuleCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_id: str
    name: str
    value: str | None = None
    unit: str
    version: str
    effective_from: str | None = None
    effective_to: str | None = None
    source: str
    confirmation_status: str
    status: Literal["selected", "eligible", "excluded", "unknown", "conflict"]
    reason: str
    checks: list[CandidateCheck] = Field(default_factory=list)


class RuleChoiceGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_id: str
    title: str
    calculation_refs: list[str] = Field(default_factory=list)
    input_refs: list[str] = Field(default_factory=list)
    field_refs: list[str] = Field(default_factory=list)
    candidates: list[RuleCandidate] = Field(default_factory=list)


class ExplanationEvidence(BaseModel):
    inputs: dict[str, FormulaInput] = Field(default_factory=dict)
    rule_choices: list[RuleChoiceGroup] = Field(default_factory=list)
    settlement_date: date


def attach_evidence(result: SettlementDecompositionResult,
                    snapshot: DecompositionSnapshot | OutpatientSpecialSnapshot) -> SettlementDecompositionResult:
    """从同一计算快照取白名单字段，不由账面支付金额倒推身份或比例。"""
    special = isinstance(snapshot, OutpatientSpecialSnapshot)
    dt = snapshot.settle_date if special else snapshot.trade.trade_date
    evidence = ExplanationEvidence(settlement_date=dt)

    def put(ref: str, name: str, value, source: str, confirmed: bool = True, reason: str | None = None):
        evidence.inputs[ref] = FormulaInput(
            input_id=input_id(ref), name=name, value=None if value is None else str(value),
            status="missing" if value is None else "verified" if confirmed else "unverified",
            source=source, reason=reason if value is not None else "原始数据未取得")

    person = snapshot.person
    if isinstance(snapshot, DecompositionSnapshot):
        put("fact.person.military_disability_level_code", "伤残待遇等级原码（0为不享受）",
            snapshot.person.military_disability_level_code, "本笔结算伤残待遇登记（既有军残待遇等级码表）")
        put("fact.person.public_medical_flag", "公务员待遇标志原码（0为享受）",
            snapshot.person.public_medical_flag, "本笔结算记录（院内字典150）")
        put("fact.person.public_medical_treatment_code", "本笔原公疗待遇通道类别（0为未选择）",
            snapshot.person.public_medical_treatment_code, "本笔结算记录（原公疗通道选择条件）")
        put("fact.person.retire_officer_flag", "退役医疗费标志", snapshot.person.retire_officer_flag, "本笔结算记录")
        put("RETIRE_OFFICER_PAY", "退役医疗费支付", snapshot.observed.retire_officer_pay, "本笔结算记录（仅作支付构成，不推导本项待遇）")
        put("T_BigillPay", "大病保险支付", snapshot.observed.bigill_pay, "本笔结算记录")
        put("NT_CivilPay", "民政救助支付", snapshot.observed.civil_pay, "本笔结算记录")
    code = person.cblb if isinstance(person, SpecialPersonProfile) else person.person_type_code
    put("fact.trade.trade_date", "结算日期", dt, "本笔结算记录")
    put("fact.person.person_type_code", "人员类别代码", code, "本笔参保登记")
    put("fact.person.retirement_category", "退休补助类别", person.retirement_category, "参保待遇资格登记")
    for ref, name, value in (
        ("fact.person.military_grade", "军残等级组", person.military_grade if isinstance(person, SpecialPersonProfile) else person.military_disability_grade),
        ("fact.person.military_eligible", "军残待遇资格", person.military_grade is not None if isinstance(person, SpecialPersonProfile) and person.military_grade is not None else None if isinstance(person, SpecialPersonProfile) else person.is_disabled_veteran),
        ("fact.person.public_eligible", "公疗待遇资格", person.civil_medical_eligible if isinstance(person, SpecialPersonProfile) else person.public_medical_eligible),
    ):
        put(ref, name, value, "参保待遇资格登记（当前映射口径）")
    evidence.inputs["fact.trade.person_type_code"] = evidence.inputs["fact.person.person_type_code"]
    put("fact.institution.h_level", "机构等级代码", snapshot.institution.h_level, "费用发生机构登记")
    if not special:
        put("fact.institution.h_type", "机构类型代码", snapshot.institution.h_type, "费用发生机构登记（社区资格依据）")
        a = snapshot.accumulation
        lower = a.prior_is_lower_bound
        proven = a.self_proven
        # 自证成立（阶段 E）：说明从"下界/未确认"升级为"院内记录已自证（恒等式核对一致）"；
        # 跨院口径不在本院库，仍待签核（不确定性与措辞同步声明）
        _proven_note = "院内记录已自证（交易后累计−交易前累计＝本笔金额，恒等式核对一致）；跨院累计口径待签核"
        put("fact.trade.prior_in_scope_fee", "交易前年度医保内累计", a.prior_in_scope_fee,
            "年度累计快照（交易前）", a.prior_in_scope_fee_is_pre_trade and not lower,
            "同人同年本院历史推导的可证下界，跨院累计未知" if lower
            else _proven_note if proven
            else None if a.prior_in_scope_fee_is_pre_trade else "累计时点或范围未确认")
        put("fact.trade.prior_fund_payment", "交易前年度基金支付累计", a.prior_fund_payment,
            "年度基金累计快照（交易前）", a.prior_fund_payment_is_pre_trade and not lower,
            "同人同年本院历史推导的可证下界，跨院累计未知" if lower
            else _proven_note if proven
            else None if a.prior_fund_payment_is_pre_trade else "累计时点或范围未确认")
    else:
        c = snapshot.cycle
        for ref, name, attr in (
            ("fact.cycle.deductible_standard", "本周期起付标准", "deductible_standard"),
            ("fact.cycle.prior_deductible_paid", "本周期交易前已交起付", "prior_cycle_deductible_paid"),
            ("fact.cycle.prior_cycle_deductible_paid", "本周期交易前已交起付", "prior_cycle_deductible_paid"),
            ("fact.cycle.prior_cycle_in_scope_total", "本周期交易前医保内累计", "prior_cycle_in_scope_total"),
            ("fact.cycle.prior_pool_fund_payment", "交易前年度统筹支付累计", "prior_annual_pool_fund_payment"),
            ("fact.cycle.prior_annual_large_fund_payment", "交易前年度大额支付累计", "prior_annual_large_fund_payment"),
        ):
            confirmed = (c.evidence_status == "confirmed" or attr in c.confirmed_fields) and attr != "deductible_standard"
            put(ref, name, getattr(c, attr), "结算周期及年度待遇快照（交易前）", confirmed,
                None if confirmed else "周期记录的标准已读取，待遇适用性与版本仍需核证" if attr == "deductible_standard" else "本字段的累计时点、范围或周期口径未确认")
        put("fact.cycle.position", "本年度结算周期位置", c.cycle_position, "结算周期记录")
        if snapshot.kidney_fixed_quota:
            put("fact.fixed.quota", "医院核定定额", snapshot.kidney_fixed_quota.quota_amount,
                "本周期医院定额记录", False, "定额参数仍待业务签核")
        put("fact.person.civil_type", "医疗救助身份代码", person.civil_type if isinstance(person, SpecialPersonProfile) else None,
            "参保医疗救助资格登记")
        for attr, name in (
            ("feein_db_pay", "医保内个人自付一的大病支付"),
            ("feeout_db_pay", "按比例先行自付的大病支付"),
            ("feein_maf_pay", "医保内剩余个人负担的救助"),
            ("feeout_maf_pay", "按比例先行自付剩余负担的救助"),
        ):
            put(f"fact.secondary.book.{attr}", name, getattr(snapshot.observed, attr), "本笔结算记录")
        secondary = snapshot.secondary_coverage
        for ref, name, value in (
            ("fact.secondary.big_ill_scope_total", "年度大病合规个人负担累计", secondary.big_ill_scope_total),
            ("fact.secondary.civil_fund_payment_total", "年度救助支付累计", secondary.civil_fund_payment_total),
            ("fact.secondary.is_post_trade", "累计为交易后快照", None if secondary.is_post_trade is None else int(secondary.is_post_trade)),
        ):
            put(ref, name, value, "年度二次保障累计快照", secondary.evidence_status == "confirmed",
                None if secondary.evidence_status == "confirmed" else "累计时点或口径未确认")
    # 出生日期原文不出快照；年龄使用已执行的判定记录，公开说明校验方式。
    age_branch = next((b for b in result.branches if b.step_id == "big_pay.age_band"), None)
    age = age_branch.condition.actual_value if age_branch and age_branch.condition else None
    put("fact.person.age", "结算日已满周岁", age,
        "参保出生日期（已隐藏）与结算日期：年份差－本年生日未到扣1", person.birth_date is not None)
    if age is not None and person.birth_date is not None:
        from calendar import isleap
        from src.runtime.policy_qa.fee_decomposition.result import CalculationRecordModel, CalculationOperandModel
        years = dt.year - person.birth_date.year
        deduction = int((dt.month, dt.day) < (person.birth_date.month, person.birth_date.day))
        leap_pending = (person.birth_date.month, person.birth_date.day) == (2, 29) and not isleap(dt.year)
        put("fact.age.year_difference", "结算年份与出生年份差", years, "参保出生日期与结算日期（原文已隐藏）")
        put("fact.age.birthday_deduction", "本年生日未到扣减", deduction, "结算月日与出生月日比较（原文已隐藏）",
            not leap_pending, "非闰年的闰日生日口径未确认" if leap_pending else None)
        result = result.model_copy(update={"calculations": [*result.calculations, CalculationRecordModel(
            calculation_id="calc.age.full_years", formula_id="age_full_years_v1", formula_version="v1",
            operands=[CalculationOperandModel(ref="fact.age.year_difference", value=str(years)),
                      CalculationOperandModel(ref="fact.age.birthday_deduction", value=str(deduction))], result=age)]})
        evidence.inputs["fact.person.age"].calculation_ref = "calc.age.full_years"
        if leap_pending:
            evidence.inputs["fact.person.age"].status = "unverified"
            evidence.inputs["fact.person.age"].reason = "非闰年的闰日生日口径未确认"
    if person.birth_date is not None:
        put("fact.person.birth_date", "出生日期", "已校验，原文隐藏", "参保登记（隐私字段）")
    for item in snapshot.items:
        for suffix, name, value in (
            ("fee", "费用金额", item.fee), ("unit_price", "单价", item.unit_price),
            ("count", "数量", item.quantity if isinstance(item, SpecialFeeLineItem) else item.count),
        ):
            put(f"fact.item.{item.line_key}.{suffix}", f"明细行号{item.line_key} · {name}", value, "本笔费用明细记录")
    from src.runtime.policy_qa.fee_decomposition.rule_choices import build_rule_choices
    evidence.rule_choices = build_rule_choices(result, snapshot, evidence)
    for group in evidence.rule_choices:
        family = group.group_id.split("-")[2] if group.group_id.startswith("rules-") and not group.group_id.startswith("rules-secondary-") else ""
        targets = {
            "DED": ["YBNQFJE"] if special else ["T_FirstPay"],
            "RATE": ["TCZHF", "TCZIF", "DEGWYZHF", "DEGWYZIF"] if special else ["T_BigPay", "T_BigSelfPay"],
            "CAP": ["TCZHF", "TCZIF", "DEGWYZHF", "DEGWYZIF"] if special else ["T_BigPay", "T_BigSelfPay"],
            "LGP": ["DEGWYZHF", "DEGWYZIF"], "LCAP": ["DEGWYZHF", "DEGWYZIF"],
            "RSUP": ["BCZHF"] if special else ["T_BCPay"],
            "DVET": ["JCZHF"] if special else ["T_JCPay"],
            "PMED": ["GFYLBCHBX"] if special else ["T_OfficalPay"],
            "MSF": ["T_BigPay"], "BIGILL": ["T_BigillPay"], "CIVIL": ["NT_CivilPay"],
        }.get(family, [])
        if group.group_id == "rules-secondary-db":
            targets = ["BIG_ILL_PAY", "FEEIN_DB_PAY", "FEEOUT_DB_PAY", "PERSON_PAYABLE"]
        if group.group_id == "rules-secondary-aid":
            targets = ["CIVIL_IN", "FEEIN_MAF_PAY", "FEEOUT_MAF_PAY", "PERSON_PAYABLE"]
        group.field_refs = [field.field_code for field in result.fields if field.field_code in targets]
    return result.model_copy(update={"explanation_evidence": evidence})
