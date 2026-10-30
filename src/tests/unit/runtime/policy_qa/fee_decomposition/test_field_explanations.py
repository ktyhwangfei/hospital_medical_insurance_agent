"""字段四要素固定说明（阶段 B）单元测试。

覆盖：
- 四模板 74 个展示字段逐一断言：金额含义齐备，四要素齐全或 boundary 显式列缺项；
- GRZIF1（自付一列未维护）：含义为"补助或二次保障前的计算构成"，边界保留诚实口径；
- 账户/现金：支付渠道语义（与个人承担同一笔钱的支付拆分，不重复相加）；
- 零金额三态：不适用 / 符合但为零 / 资格资料不足，分别出固定措辞；
- 未关联字段（beyond_cap、普通门诊链 NT_CivilPay/RETIRE_OFFICER_PAY）：boundary 列具体缺项；
- 公开载荷：字段级 explanation 与 template_explanations 进入公开视图且全量过消毒；
- 聊天同源：whole_settlement 也装载全字段固定说明，target_evidence sentence 复用同一份文字。
"""
from __future__ import annotations

import pytest

from src.config.settlement_templates import get_settlement_template
from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence
from src.runtime.policy_qa.fee_decomposition.field_explanations import (
    FieldExplanationView,
    build_field_explanation,
    chain_family,
)
from src.runtime.policy_qa.fee_decomposition.public_view import (
    build_public_view_dict,
    render_summary,
    to_public_contract_dict,
)
from src.runtime.policy_qa.fee_decomposition.settlement_facts import (
    SettlementDisplayField,
    SettlementDisplayView,
    SettlementFactsView,
)
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_public_view import (
    _field,
    _result,
)

DISPLAY_TEMPLATES = (
    "employee_outpatient", "resident_outpatient", "employee_special", "resident_special")

DISPLAY_KEYS = {
    template_id: [f.key for f in get_settlement_template(template_id).fields
                  if f.visible and f.section != "basic"]
    for template_id in DISPLAY_TEMPLATES
}
#: 任务口径：19+19+19+17=74 个展示字段
assert sum(len(keys) for keys in DISPLAY_KEYS.values()) == 74


def _cases():
    return [(template_id, key) for template_id in DISPLAY_TEMPLATES for key in DISPLAY_KEYS[template_id]]


@pytest.mark.parametrize("template_id,key", _cases())
def test_every_display_field_has_meaning_and_explicit_boundary(template_id: str, key: str):
    template_field = next(f for f in get_settlement_template(template_id).fields if f.key == key)
    explanation = build_field_explanation(
        family=template_id, template_key=key,
        field_code=template_field.field_code, label=template_field.label,
        field=None)
    if key == "retire_officer_pay":
        # 该字段只讲原单退役医疗费标志，不再写字段含义/缺证套话
        assert explanation.boundary, f"{template_id}/{key} 未给标志时须声明缺项"
        return
    assert explanation.meaning, f"{template_id}/{key} 缺金额含义"
    complete = bool(explanation.composition) and bool(explanation.basis_text)
    assert complete or explanation.boundary, f"{template_id}/{key} 四要素不齐且 boundary 未列缺项"


# ── 未关联字段：boundary 显式列具体缺项 ─────────────────────────────


@pytest.mark.parametrize("template_id", ("employee_outpatient", "resident_outpatient"))
def test_beyond_cap_declares_missing_rule_and_cumulative(template_id: str):
    explanation = build_field_explanation(
        family=template_id, template_key="beyond_cap",
        field_code=None, label="大额超封顶金额", field=None)
    assert explanation.meaning
    assert explanation.composition is None
    assert "封顶" in (explanation.boundary or "")
    assert "未产出" in (explanation.boundary or "") or "未绑定" in (explanation.boundary or "")


@pytest.mark.parametrize("template_id", ("employee_outpatient", "resident_outpatient"))
def test_outpatient_aid_pay_declares_kernel_gap(template_id: str):
    explanation = build_field_explanation(
        family=template_id, template_key="aid_pay",
        field_code="NT_CivilPay", label="救助支付", field=None)
    assert explanation.meaning
    assert "未产出" in (explanation.boundary or "")
    assert "救助" in (explanation.boundary or "")


def test_resident_outpatient_retire_officer_declares_kernel_gap():
    explanation = build_field_explanation(
        family="resident_outpatient", template_key="retire_officer_pay",
        field_code="RETIRE_OFFICER_PAY", label="退役医疗费", field=None)
    # 调用方未给标志时只声明缺项，不输出“规则未接入/无独立计算”等套话
    assert explanation.meaning is None
    assert "退役医疗费标志" in (explanation.boundary or "")


# ── GRZIF1：含义新措辞 + 边界保留诚实口径 ───────────────────────────


def _djh567_view():
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_special_mz_golden import (
        _snapshot_djh567,
    )
    from src.runtime.policy_qa.fee_decomposition.employee_outpatient_special import (
        decompose_employee_outpatient_special,
    )

    snapshot = _snapshot_djh567()
    result = attach_evidence(decompose_employee_outpatient_special(snapshot), snapshot)
    return build_public_view_dict(result, summary_text="", summary_source="template")


def test_grzif1_meaning_is_pre_subsidy_composition_and_boundary_keeps_honest_wording():
    view = _djh567_view()
    field = next(f for f in view["fields"] if f["field_code"] == "GRZIF1")
    explanation = field["explanation"]
    assert explanation is not None
    assert "补助或二次保障前的计算构成" in explanation["meaning"]
    boundary = explanation["boundary"] or ""
    assert "未维护" in boundary and "不作账面核对" in boundary
    # 不得回退为"原单读取、没有计算路径"类说法
    blob = str(explanation)
    assert "原单读取" not in blob
    assert "没有计算路径" not in blob


def test_grzif1_resident_special_688_same_wording():
    """居民门特 688（GRZIF1=279.27）：含义与边界口径与职工 567 一致。"""
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_resident_outpatient_special import (
        _snapshot,
        _split,
    )
    from src.runtime.policy_qa.fee_decomposition.resident_outpatient_special import (
        decompose_resident_outpatient_special,
    )

    snapshot = _snapshot()
    result = decompose_resident_outpatient_special(snapshot, _split())
    view = build_public_view_dict(result, summary_text="", summary_source="template")
    field = next(f for f in view["fields"] if f["field_code"] == "GRZIF1")
    assert field["calculated_amount"] == "279.27"
    explanation = field["explanation"]
    assert "补助或二次保障前的计算构成" in explanation["meaning"]
    assert "未维护" in (explanation["boundary"] or "")
    assert "不作账面核对" in (explanation["boundary"] or "")


# ── 账户/现金：支付渠道语义 ──────────────────────────────────────────


def test_account_and_cash_fields_carry_payment_channel_meaning():
    view = _djh567_view()
    for code in ("ZHZF", "XJZF"):
        field = next(f for f in view["fields"] if f["field_code"] == code)
        explanation = field["explanation"]
        assert explanation is not None, code
        assert "支付方式" in explanation["meaning"]
        assert "不重复相加" in explanation["meaning"]


def test_outpatient_account_and_cash_fields_carry_payment_channel_meaning():
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_resident_outpatient import (
        _snapshot,
    )
    from src.runtime.policy_qa.fee_decomposition.resident_outpatient import (
        decompose_resident_outpatient,
    )

    snapshot = _snapshot()
    result = attach_evidence(decompose_resident_outpatient(snapshot), snapshot)
    view = build_public_view_dict(result, summary_text="", summary_source="template")
    for code in ("T_PersonCountPay", "T_CashPay"):
        field = next(f for f in view["fields"] if f["field_code"] == code)
        assert field["explanation"] is not None, code
        assert "支付方式" in field["explanation"]["meaning"]
        assert "不重复相加" in field["explanation"]["meaning"]


# ── 零金额三态 ──────────────────────────────────────────────────────


def test_zero_amount_not_eligible_wording():
    result = _result(fields=[_field(
        field_code="T_BCPay", label="退休补充保险补助",
        check_status="not_applicable", calculated_amount=None, difference=None,
        explanation_level="unexplained", reason_code="NOT_RETIRED")])
    text = render_summary(result)
    assert "退休补充保险补助：本单不符合该待遇条件，该项待遇不适用。" in text
    view = build_public_view_dict(result, summary_text="", summary_source="template")
    explanation = view["fields"][0]["explanation"]
    assert "本单不符合该待遇条件" in (explanation["boundary"] or "")


def test_zero_amount_eligible_but_zero_wording():
    result = _result(fields=[_field(
        field_code="T_BigPay", label="大额支付",
        observed_amount="0.00", calculated_amount="0.00")])
    text = render_summary(result)
    assert "符合待遇条件，本笔金额为零" in text
    assert "本单不适用" not in text


def test_zero_amount_eligibility_unknown_wording():
    result = _result(fields=[_field(
        field_code="T_JCPay", label="军残补助",
        check_status="not_verifiable", observed_amount="0.00", calculated_amount=None,
        difference=None, explanation_level="observed_only",
        reason_code="MILITARY_ELIGIBILITY_FIELD_UNMAPPED")])
    text = render_summary(result)
    assert "资格资料不足，不能仅凭零金额判断没有资格" in text
    assert "本单不适用" not in text


# ── 公开载荷：字段 explanation + template_explanations + 消毒 ────────


def _display_view(template_id: str) -> SettlementDisplayView:
    template = get_settlement_template(template_id)
    return SettlementDisplayView(
        template_id=template.template_id, version=template.version, title=template.title,
        layout_status=template.layout_status,
        fields=[SettlementDisplayField(
            key=f.key, label=f.label, field_code=f.field_code, section=f.section,
            row=f.row, column=f.column, span=f.span, scope=f.scope,
            value=None, source_kind="record", status="missing")
            for f in template.fields if f.visible])


def test_template_explanations_cover_every_visible_template_field():
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_special_mz_golden import (
        _snapshot_djh567,
    )
    from src.runtime.policy_qa.fee_decomposition.employee_outpatient_special import (
        decompose_employee_outpatient_special,
    )

    snapshot = _snapshot_djh567()
    result = attach_evidence(decompose_employee_outpatient_special(snapshot), snapshot)
    facts = SettlementFactsView(chain="special", display_template=_display_view("employee_special"))
    view = build_public_view_dict(
        result, summary_text="", summary_source="template", settlement_facts=facts)
    explanations = view["template_explanations"]
    assert set(explanations) == set(DISPLAY_KEYS["employee_special"])
    for key, explanation in explanations.items():
        if key == "retire_officer_pay":
            # 退役医疗费只给“原单标志”这一句事实，不再要求字段含义/政策依据/缺项套话
            assert "退役医疗费标志" in (explanation["composition"] or ""), key
            continue
        assert explanation["meaning"], key
        complete = bool(explanation["composition"]) and bool(explanation["basis_text"])
        assert complete or explanation["boundary"], key


def test_field_explanation_texts_sanitized():
    result = _result(fields=[_field(field_code="T_BigPay", label="大额支付")])
    view = to_public_contract_dict(
        result, summary_text="", summary_source="template",
        sanitize=lambda value: str(value).replace("基金", "已脱敏"))
    explanation = view["fields"][0]["explanation"]
    assert explanation is not None
    for part in ("meaning", "composition", "basis_text", "boundary"):
        text = explanation[part]
        assert text is None or "基金" not in text, part
    assert "已脱敏" in (explanation["meaning"] or "")


def test_field_explanation_survives_public_contract_validation():
    from src.runtime.policy_qa.public_contract import FeeDecompositionPublic

    result = _result(fields=[_field(field_code="T_BigPay", label="大额支付")])
    view = to_public_contract_dict(
        result, summary_text="", summary_source="template", sanitize=str)
    public = FeeDecompositionPublic.model_validate(view)
    explanation = public.fields[0].explanation
    assert isinstance(explanation, FieldExplanationView)
    assert explanation.meaning


# ── 聊天同源：whole_settlement 装载 + target_evidence sentence 复用 ──


def test_whole_settlement_loads_all_field_explanations():
    from src.runtime.policy_qa.fee_decomposition.model_explanation import build_model_input

    result = _djh567_result_public()
    payload = build_model_input(result, "解释这笔结算")
    assert payload.target_evidence, "整单问题必须装载全字段固定说明"
    grzif1 = next(item for item in payload.target_evidence if item.field_code == "GRZIF1")
    assert "补助或二次保障前的计算构成" in (grzif1.sentence or "")
    assert "未维护" in (grzif1.sentence or "")


def test_target_evidence_sentence_reuses_panel_explanation_text():
    """同一字段：聊天 sentence 与面板 explanation 同源同文。"""
    from src.runtime.policy_qa.fee_decomposition.model_explanation import build_model_input

    public = _djh567_result_public()
    payload = build_model_input(public, "统筹基金支付是怎么算的？")
    evidence = next(item for item in payload.target_evidence if item.field_code == "TCZHF")
    field = next(f for f in public.fields if f.field_code == "TCZHF")
    assert field.explanation is not None
    assert field.explanation.meaning in (evidence.sentence or "")


def _djh567_result_public():
    from src.runtime.policy_qa.public_contract import FeeDecompositionPublic
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_special_mz_golden import (
        _snapshot_djh567,
    )
    from src.runtime.policy_qa.fee_decomposition.employee_outpatient_special import (
        decompose_employee_outpatient_special,
    )

    snapshot = _snapshot_djh567()
    result = attach_evidence(decompose_employee_outpatient_special(snapshot), snapshot)
    return FeeDecompositionPublic.model_validate(to_public_contract_dict(
        result, summary_text=render_summary(result), summary_source="template",
        sanitize=str))


def test_chain_family_mapping():
    assert chain_family("employee_outpatient_v1") == "employee_outpatient"
    assert chain_family("resident_outpatient_v1") == "resident_outpatient"
    assert chain_family("employee_outpatient_special_v1") == "employee_special"
    assert chain_family("resident_outpatient_special_v1") == "resident_special"
    assert chain_family("employee_special_fixed_kidney_v1") == "employee_special"
    assert chain_family("unknown") is None


def test_fund_total_explanation_points_to_channel_composition():
    """基金支付合计（账面勾稽字段）的固定说明指向有独立计算的非零渠道字段（阶段 F 验收缺口）。

    用户问「基金支付金额 420 怎么算」时，固定说明不能只答"账面勾稽"——
    本笔全部基金来自大额基金渠道且该渠道有独立计算，应指引到渠道字段的计算构成。
    """
    result = _result(fields=[
        _field(field_code="T_FundPay", label="基金支付金额", check_type="identity_check",
               check_status="not_verifiable", observed_amount="420.00",
               calculated_amount=None, difference=None, explanation_level="observed_only"),
        _field(field_code="T_BigPay", label="当次门诊大额基金支付金额",
               check_type="independent_recalculation", check_status="matched",
               observed_amount="420.00", calculated_amount="420.00",
               calculation_refs=["calc.big_pay"]),
    ])
    facts = SettlementFactsView(
        chain="outpatient", display_template=_display_view("employee_outpatient"))
    view = build_public_view_dict(
        result, summary_text="", summary_source="template", settlement_facts=facts)
    fund = next(f for f in view["fields"] if f["field_code"] == "T_FundPay")
    composition = fund["explanation"]["composition"] or ""
    assert "账面勾稽" in composition  # 诚实口径保留
    assert "当次门诊大额基金支付金额" in composition
    assert "420.00" in composition
    # 面板 template_explanations 与字段级 explanation 同源同文
    assert "当次门诊大额基金支付金额" in view["template_explanations"]["fund_total"]["composition"]


def test_fund_total_without_computed_channel_keeps_plain_reconciliation_wording():
    """无非零已计算渠道时维持原勾稽措辞，不编造指引。"""
    result = _result(fields=[
        _field(field_code="T_FundPay", label="基金支付金额", check_type="identity_check",
               check_status="not_verifiable", observed_amount="0.00",
               calculated_amount=None, difference=None, explanation_level="observed_only"),
        _field(field_code="T_BigPay", label="当次门诊大额基金支付金额",
               check_type="independent_recalculation", check_status="matched",
               observed_amount="0.00", calculated_amount="0.00"),
    ])
    facts = SettlementFactsView(
        chain="outpatient", display_template=_display_view("employee_outpatient"))
    view = build_public_view_dict(
        result, summary_text="", summary_source="template", settlement_facts=facts)
    fund = next(f for f in view["fields"] if f["field_code"] == "T_FundPay")
    composition = fund["explanation"]["composition"] or ""
    assert "当次门诊大额基金支付金额」" not in composition


# ── 评审问题 4：医保外/自付二固定含义修正 ─────────────────────────────


def test_fee_out_meaning_is_stage_definition_not_final_burden():
    """医保外含义：基本医保划分口径的阶段金额，不得说成"由个人全额承担"。"""
    explanation = build_field_explanation(
        family="resident_special", template_key="fee_out",
        field_code="TSBYBW", label="医疗保险范围外金额", field=None)
    assert explanation.meaning
    assert "范围外金额" in explanation.meaning
    assert "最终个人负担还需结合本单后续保障" in explanation.meaning
    assert "由个人全额承担" not in explanation.meaning


def test_688_fee_out_composition_lists_actual_secondary_coverage():
    """688：医保外 69.90 中大病覆盖 45.43、救助覆盖 24.47，最终个人承担 0。"""
    field = dict(check_status="matched", reason_code=None,
                 check_type="independent_recalculation",
                 observed_amount="69.90", calculated_amount="69.90",
                 brief="医保外费用合计＝69.90 元", basis={"source_titles": []},
                 conclusion="recalculated", conclusion_text="", explanation_reason=None)
    siblings = {
        "FEEOUT_DB_PAY": {"observed_amount": "45.43"},
        "FEEOUT_MAF_PAY": {"observed_amount": "24.47"},
    }
    explanation = build_field_explanation(
        family="resident_special", template_key="fee_out",
        field_code="TSBYBW", label="医疗保险范围外金额",
        field=field, siblings=siblings)
    assert explanation.composition
    assert "大病保险支付覆盖 45.43 元" in explanation.composition
    assert "医疗救助支付覆盖 24.47 元" in explanation.composition
    assert "剩余由个人承担 0.00 元" in explanation.composition


def test_fee_out_without_coverage_keeps_plain_composition():
    """无二次保障分量的单（0408）：不编造覆盖句。"""
    field = dict(check_status="matched", reason_code=None,
                 check_type="independent_recalculation",
                 observed_amount="240.00", calculated_amount="240.00",
                 brief="医保外费用合计＝240.00 元", basis={"source_titles": []},
                 conclusion="recalculated", conclusion_text="", explanation_reason=None)
    explanation = build_field_explanation(
        family="resident_outpatient", template_key="fee_out",
        field_code="T_FeeOut", label="医疗保险范围外金额",
        field=field, siblings={})
    assert explanation.composition == "医保外费用合计＝240.00 元"


def test_fee_out_coverage_skipped_when_book_relation_breaks():
    """覆盖合计超过范围外金额（账面关系不成立）时不编造覆盖结论。"""
    field = dict(check_status="matched", reason_code=None,
                 check_type="independent_recalculation",
                 observed_amount="69.90", calculated_amount="69.90",
                 brief="医保外费用合计＝69.90 元", basis={"source_titles": []},
                 conclusion="recalculated", conclusion_text="", explanation_reason=None)
    siblings = {
        "FEEOUT_DB_PAY": {"observed_amount": "45.43"},
        "FEEOUT_MAF_PAY": {"observed_amount": "80.00"},
    }
    explanation = build_field_explanation(
        family="resident_special", template_key="fee_out",
        field_code="TSBYBW", label="医疗保险范围外金额",
        field=field, siblings=siblings)
    assert "后续保障" not in (explanation.composition or "")


def test_self_pay_2_meaning_covers_proportional_and_over_limit():
    """自付二含义覆盖本单实际计入的比例先行与超限价部分，且说明已含于医保外。"""
    explanation = build_field_explanation(
        family="resident_outpatient", template_key="self_pay_2",
        field_code="T_SelfPay2", label="个人支付自付（二）金额", field=None)
    assert explanation.meaning
    assert "比例先行自付" in explanation.meaning
    assert "超限价自付" in explanation.meaning
    assert "不重复相加" in explanation.meaning


# ── 退役医疗费 0 元：条件与不满足点（原单标志可核对）─────────────────

def _retire_officer_public(flag: str | None, retire_pay: str = "0.00"):
    from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence
    from src.runtime.policy_qa.fee_decomposition.public_view import build_public_view_dict
    from src.runtime.policy_qa.fee_decomposition.result import (
        AnswerConstraints, CoverageSummary, DecompositionProfile,
        FieldExplanationModel, SettlementDecompositionResult)
    from src.runtime.policy_qa.public_contract import FeeDecompositionPublic
    from src.runtime.policy_qa.fee_decomposition.settlement_facts import (
        SettlementDisplayField, SettlementDisplayView, SettlementFactsItem,
        SettlementFactsView)
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_resident_outpatient_special import (
        _snapshot, _split)
    from src.runtime.policy_qa.fee_decomposition.resident_outpatient_special import (
        decompose_resident_outpatient_special)

    snapshot = _snapshot()
    result = decompose_resident_outpatient_special(snapshot, _split())
    display = SettlementDisplayView(
        template_id="resident_special", version="v1", title="结算单",
        layout_status="provisional",
        fields=[SettlementDisplayField(
            key="retire_officer_pay", label="退役医疗费", field_code="RETIRE_OFFICER_PAY",
            section="transaction", row=10, column=1, span=1,
            scope="patient_actual", value=retire_pay, source_kind="unmapped",
            status="unmapped")])
    facts = SettlementFactsView(
        chain="outpatient", identifier="T1", retire_officer_flag=flag,
        display_template=display,
        items=[SettlementFactsItem(label="退役医疗费", value=retire_pay)])
    view = build_public_view_dict(attach_evidence(result, snapshot),
                                  summary_text="", summary_source="template",
                                  settlement_facts=facts)
    return FeeDecompositionPublic.model_validate(view)


def test_retire_officer_zero_lists_recorded_flag():
    """原单退役医疗费标志=0 时，用一句事实说明“该渠道未触发”。"""
    public = _retire_officer_public("0")
    view = public.template_explanations["retire_officer_pay"]
    text = "；".join(part for part in (view.meaning, view.composition, view.boundary) if part)
    assert "退役医疗费标志为 0" in text
    assert "未接入" not in text
    assert view.boundary is None
    from src.runtime.policy_qa.fee_decomposition.model_explanation import explain_decomposition
    answer = explain_decomposition(public, "退役医疗费为什么是0").answer
    assert "退役医疗费标志为 0" in answer
    assert "0.00" in answer


def test_retire_officer_missing_flag_is_declared_as_insufficient_data():
    public = _retire_officer_public(None)
    view = public.template_explanations["retire_officer_pay"]
    text = "；".join(part for part in (view.meaning, view.composition, view.boundary) if part)
    assert "未提供退役医疗费标志" in text


def test_retire_officer_answer_is_concise_flag_only():
    """退役医疗费 0 元只讲原单标志，不再罗列缺证条件与“按原单记录列示”等填充语。"""
    public = _retire_officer_public("0")
    from src.runtime.policy_qa.fee_decomposition.model_explanation import explain_decomposition
    answer = explain_decomposition(public, "退役医疗费为什么是0").answer
    assert "退役医疗费标志为 0" in answer or "退役医疗费标志为0" in answer
    for fluff in ("按原单记录列示", "退役/军休人员类别", "未接入可核对规则",
                  "不能据此确认完整资格口径", "本项无独立待遇计算",
                  "该渠道未触发", "属基金支付口径"):
        assert fluff not in answer, fluff
    assert len(answer) < 120
