"""只执行有明确业务含义和证据前提的确定性门诊结算核验。"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from itertools import combinations
import re

from .models import (
    AmountCheck,
    ContextCheck,
    FieldExplanation,
    MoneyState,
    OutpatientSettlementContext,
    OutpatientVerificationResult,
    PolicyEvidence,
)


CENT = Decimal("0.01")
MONEY_FIELDS = (
    ("total_amount", "费用总金额"),
    ("in_scope_amount", "医保范围内金额"),
    ("self_pay_one", "个人自付一"),
    ("deductible_amount", "起付金额"),
    ("beyond_cap_amount", "超封顶金额"),
    ("account_payment", "个人账户支付"),
    ("cash_payment", "现金支付"),
    ("big_disease_payment", "大病支付"),
    ("retired_medical_payment", "退役医疗支付"),
    ("unit_supplement_payment", "单位补充医疗支付"),
    ("personal_total_amount", "个人支付总金额"),
    ("out_of_scope_amount", "医保范围外金额"),
    ("self_pay_two", "个人自付二"),
    ("large_self_pay", "大额自付"),
    ("fund_total_amount", "基金支付总金额"),
    ("large_fund_payment", "门诊大额基金支付"),
    ("disabled_soldier_payment", "军残补助支付"),
    ("supplementary_insurance_payment", "补充保险支付"),
    ("assistance_payment", "医疗救助支付"),
)


def money(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def _yuan(value: object) -> str:
    """勾稽算式用金额展示；缺失时明确标为未返回。"""
    amount = money(value)
    return "未返回" if amount is None else f"{amount} 元"


# 支付方渠道（结算单原始字段口径）；组合关系不写死公式，逐单求解验证成员关系
FUND_CHANNELS = (
    ("large_fund_payment", "门诊大额基金支付"),
    ("supplementary_insurance_payment", "补充保险支付"),
    ("unit_supplement_payment", "单位补充医疗支付"),
    ("big_disease_payment", "大病支付"),
    ("retired_medical_payment", "退役医疗支付"),
    ("disabled_soldier_payment", "军残补助支付"),
    ("assistance_payment", "医疗救助支付"),
)


def _matching_channel_combos(
    context: OutpatientSettlementContext, target: Decimal
) -> list[list[tuple[str, Decimal]]]:
    """在非零支付渠道中穷举和恰为 target 的组合（渠道 ≤7，子集枚举足够快）。"""
    channels = [
        (label, amount)
        for field, label in FUND_CHANNELS
        if (amount := money(getattr(context, field))) not in (None, Decimal("0.00"))
    ]
    hits: list[list[tuple[str, Decimal]]] = []
    for size in range(1, len(channels) + 1):
        for combo in combinations(channels, size):
            if sum((value for _, value in combo), Decimal("0.00")) == target:
                hits.append(list(combo))
    return hits


def _combo_text(combo: list[tuple[str, Decimal]]) -> str:
    return " + ".join(f"{label} {value} 元" for label, value in combo)


def _subtracted_combo_text(combo: list[tuple[str, Decimal]]) -> str:
    """被减渠道清单：医保内抵扣渠道均为减项，逐个面连减号。"""
    return " - ".join(f"{label} {value} 元" for label, value in combo)


def decompose_personal_payment(
    context: OutpatientSettlementContext,
) -> tuple[list[str], list[str]]:
    """逐层费用分解：每步只在结算字段能证明成员关系时归因到渠道，否则降级为事实陈述。

    设计约束（SKILL.md 口径）：统筹自付 = 自付一 + 自付二；自付一由医保内金额与
    基金支付分解，自付二由费用明细先自付合计分解；专项补助组合不写死公式。
    """
    lines: list[str] = []
    uncertainties: list[str] = []
    total = money(context.total_amount)
    in_scope = money(context.in_scope_amount)
    out_scope = money(context.out_of_scope_amount)
    sp1 = money(context.self_pay_one)
    sp2 = money(context.self_pay_two)
    personal_total = money(context.personal_total_amount)

    if total is not None and in_scope is not None and out_scope is not None:
        lines.append(
            f"费用总金额 {_yuan(total)} = 医保范围内金额 {_yuan(in_scope)}"
            f" + 医保范围外金额 {_yuan(out_scope)}"
        )
    if in_scope is not None and sp1 is not None:
        deductible = money(context.deductible_amount)
        big_self_pay = money(context.large_self_pay)
        # 恒等式「自付一 = 起付 + 统筹段个人自付」逐单验证成立且起付非零时，
        # 拆到根（起付段占大头时这是「为什么这么多」的真实原因）；
        # 否则回退到基金渠道求解（居民/补充保险/救助结构不同，恒等式未必成立）。
        if (
            deductible not in (None, Decimal("0.00"))
            and big_self_pay is not None
            and abs(sp1 - deductible - big_self_pay) <= CENT
        ):
            beyond_line = in_scope - deductible
            lines.append(
                f"个人自付一 {_yuan(sp1)} = 起付金额 {_yuan(deductible)}"
                f" + 大额自付 {_yuan(big_self_pay)}"
                f"（医保范围内 {_yuan(in_scope)} 中，起付线内 {_yuan(deductible)} 全额自付，"
                f"超线 {_yuan(beyond_line)} 按政策比例分担）"
            )
        else:
            # 起付版不可用时，大额自付单独立行（术语与结算单字段 T_BigSelfPay 对齐）
            if big_self_pay not in (None, Decimal("0.00")):
                ded_note = (
                    f"、起付金额 {_yuan(deductible)}"
                    if deductible is not None
                    else ""
                )
                lines.append(
                    f"大额自付 {_yuan(big_self_pay)} 为医保范围内超起付线部分的"
                    f"个人分担（本单医保范围内 {_yuan(in_scope)}{ded_note}）"
                )
            offset = in_scope - sp1
            if offset == Decimal("0.00"):
                lines.append(
                    f"个人自付一 {_yuan(sp1)} = 医保范围内金额 {_yuan(in_scope)}（无基金类抵扣）"
                )
            else:
                combos = _matching_channel_combos(context, offset) if offset > 0 else []
                if len(combos) == 1:
                    lines.append(
                        f"个人自付一 {_yuan(sp1)} = 医保范围内金额 {_yuan(in_scope)}"
                        f" - {_subtracted_combo_text(combos[0])}"
                    )
                else:
                    lines.append(
                        f"个人自付一 {_yuan(sp1)} 为医保范围内金额 {_yuan(in_scope)}"
                        f" 扣除基金类抵扣 {_yuan(offset)} 后的部分"
                    )
                    if not combos:
                        uncertainties.append(
                            f"医保范围内基金抵扣 {_yuan(offset)} 无法归因到具体支付渠道，"
                            "自付一分解待人工核对。"
                        )
    if sp2 is not None:
        if sp2 == Decimal("0.00"):
            lines.append(f"个人自付二 {_yuan(sp2)}（无先自付费用）")
        else:
            items = [
                (str(item.get("ItemName") or "未命名项目"), money(item.get("FeeItem_SelfPay2")))
                for item in context.fee_items
                if money(item.get("FeeItem_SelfPay2")) not in (None, Decimal("0.00"))
            ]
            if items:
                detail = " + ".join(f"{name} {value} 元" for name, value in items)
                lines.append(f"个人自付二 {_yuan(sp2)} = 费用明细先自付合计：{detail}")
            else:
                lines.append(f"个人自付二 {_yuan(sp2)}（费用明细未返回，无法拆解到项目）")
    if sp1 is not None and sp2 is not None and personal_total is not None:
        account = money(context.account_payment)
        cash = money(context.cash_payment)
        channel_note = ""
        if account is not None and cash is not None:
            channel_note = (
                f"；个人账户支付 {_yuan(account)} + 现金支付 {_yuan(cash)}"
            )
        combined = sp1 + sp2
        gap = combined - personal_total
        if gap == Decimal("0.00"):
            lines.append(
                f"个人支付总金额 {_yuan(personal_total)} = 统筹自付（自付一 + 自付二）"
                f"{_yuan(combined)}，全部由个人承担{channel_note}"
            )
        elif gap > Decimal("0.00"):
            combos = _matching_channel_combos(context, gap)
            if len(combos) == 1:
                lines.append(
                    f"个人支付总金额 {_yuan(personal_total)} = 统筹自付（自付一 + 自付二）"
                    f"{_yuan(combined)} - {_combo_text(combos[0])}（该部分由基金/专项渠道替个人承担{channel_note}）"
                )
            else:
                lines.append(
                    f"统筹自付（自付一 + 自付二）{_yuan(combined)} 与个人支付总金额"
                    f" {_yuan(personal_total)} 差额 {_yuan(gap)}，无法归因到具体支付渠道"
                )
                uncertainties.append("统筹自付与个人支付总金额的差额渠道待人工核对。")
        else:
            lines.append(
                f"统筹自付（自付一 + 自付二）{_yuan(combined)} 低于个人支付总金额"
                f" {_yuan(personal_total)}，差异 {_yuan(-gap)} 待人工核对"
            )
            uncertainties.append("统筹自付低于个人支付总金额，金额口径异常，待人工核对。")
    return lines, uncertainties


def state_of(value: object, *, applicable: bool | None = None) -> MoneyState:
    if applicable is False:
        return "not_applicable"
    amount = money(value)
    if amount is None:
        return "missing"
    return "reported_zero" if amount == 0 else "non_zero"


def _amount_check(
    name: str, equation: str, detail: str, actual: object, expected: object
) -> AmountCheck:
    actual_amount = money(actual)
    expected_amount = money(expected)
    if actual_amount is None or expected_amount is None:
        return AmountCheck(
            name=name, equation=equation, detail=detail,
            actual=actual_amount, expected=expected_amount,
            difference=None, status="not_evaluable",
        )
    difference = (actual_amount - expected_amount).quantize(CENT)
    return AmountCheck(
        name=name, equation=equation, detail=detail,
        actual=actual_amount, expected=expected_amount,
        difference=difference,
        status="passed" if abs(difference) <= CENT else "failed",
    )


def _deductible_threshold(evidence: list[dict]) -> Decimal | None:
    """从起付线类政策证据中提取门槛金额；无法解析时返回 None。"""
    for item in evidence:
        if item.get("rule_type") != "起付线":
            continue
        for raw in (item.get("rule_value"), item.get("amount")):
            if raw is None:
                continue
            digits = re.findall(r"\d+(?:\.\d+)?", str(raw))
            if digits:
                return money(digits[0])
    return None


def explain_deductible_progress(
    context: OutpatientSettlementContext,
    policy_evidence: list[dict],
) -> tuple[list[str], list[str]]:
    """起付线解读：年度累计口径下解释「为什么起付金额为 0 但基金仍在支付」。

    仅用结算单原始字段（本笔起付金额、结算前年度医保内累计、门诊大额基金支付）
    与起付线政策证据门槛；证据缺失时降级为事实陈述并标不确定性。
    """
    lines: list[str] = []
    uncertainties: list[str] = []
    deductible = money(context.deductible_amount)
    before = money(context.additional_metrics.get("TB_FeeIn"))
    after = money(context.additional_metrics.get("TA_FeeIn"))
    big_fund = money(context.large_fund_payment)
    threshold = _deductible_threshold(policy_evidence)
    threshold_note = f"（政策起付线 {threshold} 元）" if threshold is not None else ""

    if deductible is None or before is None:
        return lines, uncertainties
    if deductible == Decimal("0.00"):
        if before > Decimal("0.00"):
            fund_note = (
                f"，门诊大额基金支付 {_yuan(big_fund)} 按政策比例正常支付"
                if big_fund not in (None, Decimal("0.00"))
                else ""
            )
            lines.append(
                f"本笔起付金额 0.00 元：门诊起付线按年度累计口径{threshold_note}，"
                f"结算前年度医保内累计 {_yuan(before)} 已越过起付线，"
                f"起付义务已在年度内此前结算中履行，本笔不再重复收取起付{fund_note}"
            )
        else:
            lines.append(
                "本笔起付金额 0.00 元且结算前年度医保内累计为 0，"
                "未检索到免起付资格标志，起付口径待人工核对"
            )
            uncertainties.append(
                "起付金额为 0 且年度累计为 0，缺少免起付资格证据，待人工核对。"
            )
    else:
        after_note = (
            f"（结算前 {_yuan(before)} → 结算后 {_yuan(after)}）"
            if after is not None
            else f"（结算前 {_yuan(before)}）"
        )
        lines.append(
            f"本笔收取起付金额 {_yuan(deductible)}，计入年度医保内累计{after_note}{threshold_note}"
        )
    if threshold is None:
        uncertainties.append(
            "未检索到本人群门诊起付线金额政策，具体门槛值以医保经办口径为准。"
        )
    return lines, uncertainties


def explain_cap_progress(
    context: OutpatientSettlementContext,
    policy_evidence: list[dict],
) -> tuple[list[str], list[str]]:
    """封顶与大额段解读：只陈述结算单年度累计与本笔支付事实。

    证据库中的封顶线规则均为住院/统筹口径，无门诊大额封顶门槛，
    因此距封顶剩余额度不猜测，声明不确定性由医保经办口径确认。
    """
    _ = policy_evidence  # 门槛解析暂不可用：住院封顶与门诊大额口径不同，不引用
    lines: list[str] = []
    uncertainties: list[str] = []
    before = money(context.additional_metrics.get("TB_BigPay"))
    after = money(context.additional_metrics.get("TA_BigPay"))
    beyond = money(context.beyond_cap_amount)
    big_fund = money(context.large_fund_payment)
    if before is None and after is None and beyond is None:
        return lines, uncertainties
    progress = (
        f"年度大额支付累计：结算前 {_yuan(before)} → 结算后 {_yuan(after)}；"
        if before is not None and after is not None
        else ""
    )
    if beyond not in (None, Decimal("0.00")):
        fund_note = (
            f"，本笔大额基金支付 {_yuan(big_fund)}"
            if big_fund not in (None, Decimal("0.00"))
            else "，本笔大额基金支付 0.00 元"
        )
        lines.append(
            f"本笔超封顶金额 {_yuan(beyond)}：年度大额支付累计已达上限，"
            f"超出部分医保基金不再支付、由个人承担{fund_note}"
        )
        if progress:
            lines.append(progress.rstrip("；"))
    elif big_fund not in (None, Decimal("0.00")):
        lines.append(
            f"{progress}本笔大额基金支付 {_yuan(big_fund)} 正常报销，本笔未触发超封顶"
        )
        uncertainties.append(
            "未检索到门诊大额封顶线金额政策，距封顶剩余额度以医保经办口径为准。"
        )
    return lines, uncertainties


def verify_settlement(
    context: OutpatientSettlementContext,
    *,
    scenario_id: str = "overall-settlement-verification",
    policy_evidence: list[dict] | None = None,
    money_fields: set[str] | None = None,
    required_money_fields: set[str] | None = None,
) -> OutpatientVerificationResult:
    """核验一笔门诊结算；证据不足时只陈述事实，不猜政策公式。"""
    evidence = [PolicyEvidence.model_validate(item) for item in (policy_evidence or [])]
    checks: list[AmountCheck] = []
    if context.in_scope_amount is not None and context.out_of_scope_amount is not None:
        checks.append(_amount_check(
            "总费用医保内外勾稽", "费用总金额 = 医保范围内金额 + 医保范围外金额",
            f"{_yuan(context.total_amount)} = {_yuan(context.in_scope_amount)} + {_yuan(context.out_of_scope_amount)}",
            context.total_amount, context.in_scope_amount + context.out_of_scope_amount,
        ))
    if context.fund_total_amount is not None and context.personal_total_amount is not None:
        checks.append(_amount_check(
            "总费用支付方勾稽", "费用总金额 = 基金支付总金额 + 个人支付总金额",
            f"{_yuan(context.total_amount)} = {_yuan(context.fund_total_amount)} + {_yuan(context.personal_total_amount)}",
            context.total_amount, context.fund_total_amount + context.personal_total_amount,
        ))
    self_pay_two_items = [
        money(item.get("FeeItem_SelfPay2"))
        for item in context.fee_items
        if item.get("FeeItem_SelfPay2") is not None
    ]
    if self_pay_two_items:
        checks.append(_amount_check(
            "个人自付二明细勾稽",
            "个人自付二 = 各费用明细先自付金额之和",
            f"{_yuan(context.self_pay_two)} = "
            + " + ".join(_yuan(item) for item in self_pay_two_items),
            context.self_pay_two,
            sum(self_pay_two_items, Decimal("0.00")),
        ))
    if context.account_payment is not None and context.cash_payment is not None:
        checks.append(_amount_check(
            "个人支付渠道勾稽", "个人支付总金额 = 个人账户支付 + 现金支付",
            f"{_yuan(context.personal_total_amount)} = {_yuan(context.account_payment)} + {_yuan(context.cash_payment)}",
            context.personal_total_amount, context.account_payment + context.cash_payment,
        ))
    ratio_rule = next(
        (
            item for item in evidence
            if item.payment_ratio is not None
            and item.calculation_base == "in_scope_minus_deductible"
        ),
        None,
    )
    if ratio_rule and context.in_scope_amount is not None and context.deductible_amount is not None:
        checks.append(_amount_check(
            "门诊大额基金支付比例",
            "门诊大额基金支付 = (医保范围内金额 - 起付金额) × 政策支付比例",
            f"{_yuan(context.large_fund_payment)} = ({_yuan(context.in_scope_amount)} - {_yuan(context.deductible_amount)}) × {ratio_rule.payment_ratio}",
            context.large_fund_payment,
            (context.in_scope_amount - context.deductible_amount) * ratio_rule.payment_ratio,
        ))

    evidence_ids = list(dict.fromkeys(item.source_id for item in evidence))
    field_explanations = []
    fields_to_explain = MONEY_FIELDS if money_fields is None else (
        item for item in MONEY_FIELDS if item[0] in money_fields
    )
    for field, label in fields_to_explain:
        value = getattr(context, field)
        applicable = context.applicability.get(field)
        state = state_of(value, applicable=applicable)
        explanations = {
            "non_zero": f"结算数据明确记录了{label}。",
            "reported_zero": f"结算数据明确记录{label}为 0 元，不能仅据此推断无待遇资格。",
            "missing": f"结算数据未返回{label}。",
            "not_applicable": f"结算资格事实标记{label}不适用。",
        }
        field_explanations.append(FieldExplanation(
            field_name=label,
            value=money(value),
            state=state,
            applicable=applicable,
            explanation=explanations[state],
            citations=[
                "settlement-data",
                *(evidence_ids if state == "not_applicable" else []),
            ],
        ))
    uncertainties: list[str] = []
    uncertainties.extend(context.data_quality_warnings)
    if not evidence:
        uncertainties.append("未提供适用于本次结算的人群、险种、机构和日期政策证据。")
    if money(context.unit_supplement_payment) not in {None, Decimal("0.00")} and not any(
        item.benefit_type == "单位补充医疗" for item in evidence
    ):
        uncertainties.append("单位补充医疗支付有实际金额，但缺少单位补充政策公式。")
    if any(item.state == "missing" for item in field_explanations):
        uncertainties.append("部分结算字段缺失，未将缺失值按 0 元处理。")

    context_checks = [
        ContextCheck(
            name=label,
            value=getattr(context, field),
            status="present" if getattr(context, field) is not None else "missing",
        )
        for field, label in (
            ("insurance_type", "险种"),
            ("person_type", "人员类别"),
            ("service_type", "医疗类别"),
            ("hospital_level", "医疗机构等级"),
            ("settlement_date", "结算日期"),
        )
    ]
    if any(item.status == "missing" for item in context_checks):
        uncertainties.append("部分待遇适用上下文缺失，不能据此确认政策是否适用。")

    anomalies = [
        f"{item.name}差额为 {item.difference} 元。"
        for item in checks if item.status == "failed"
    ]
    required_fields = {"total_amount"} if required_money_fields is None else required_money_fields
    core_amount_missing = any(getattr(context, field) is None for field in required_fields)
    if context.record_found is False or core_amount_missing:
        status = "unavailable"
    elif anomalies or uncertainties:
        status = "partial"
    else:
        status = "complete"
    return OutpatientVerificationResult(
        status=status,
        scenario_id=scenario_id,
        summary=(
            "结算记录或场景核心金额不可用。" if status == "unavailable"
            else "金额勾稽存在差异，需人工复核。" if anomalies
            else "已完成可用门诊结算金额勾稽。"
        ),
        context_checks=context_checks,
        amount_checks=checks,
        field_explanations=field_explanations,
        anomalies=anomalies,
        citations=evidence_ids,
        uncertainties=uncertainties,
        next_actions=["请医保经办人员核对原始结算单和适用政策。"] if anomalies or uncertainties else [],
    )
