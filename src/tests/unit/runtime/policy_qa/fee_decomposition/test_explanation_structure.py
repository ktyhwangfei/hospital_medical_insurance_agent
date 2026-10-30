"""解释结构（Issue #84）：结论分级、金额口径、依据链、缺口关联、环节完整性。"""
from __future__ import annotations

from datetime import date

from src.runtime.policy_qa.fee_decomposition.explanation_evidence import (
    ExplanationEvidence,
    FormulaInput,
    RuleCandidate,
    RuleChoiceGroup,
)
from src.runtime.policy_qa.fee_decomposition.public_view import _conclusion_of, build_public_view_dict
from src.runtime.policy_qa.fee_decomposition.result import (
    AnswerConstraints,
    BranchConditionModel,
    BranchTraceModel,
    CalculationOperandModel,
    CalculationRecordModel,
    CoverageSummary,
    DecompositionProfile,
    FieldExplanationModel,
    SettlementDecompositionResult,
    UncertaintyModel,
)


def _field(code: str, label: str, refs: tuple[str, ...] = (), **overrides) -> FieldExplanationModel:
    base = dict(
        field_code=code,
        label=label,
        check_type="independent_recalculation",
        check_status="matched",
        observed_amount="1.00",
        calculated_amount="1.00",
        difference="0.00",
        explanation_level="causally_explained",
        calculation_refs=list(refs),
    )
    return FieldExplanationModel(**(base | overrides))


def _calc(cid: str, *, rounding_rule: str = "not_applicable", result: str = "1.00",
          operands: tuple[CalculationOperandModel, ...] = ()) -> CalculationRecordModel:
    return CalculationRecordModel(
        calculation_id=cid, formula_id="f", formula_version="v1", operands=list(operands),
        unrounded_result=result, rounding_rule=rounding_rule, result=result)


def _group(confirmation: str) -> RuleChoiceGroup:
    return RuleChoiceGroup(
        group_id="rules-rate", title="大额基金支付比例", calculation_refs=["calc.pay"],
        candidates=[RuleCandidate(
            rule_id="EOP-RATE-1", name="门诊大额支付比例", value="70", unit="%", version="2010",
            effective_from="2010-05-01", effective_to=None, source="mz.docx §门诊大额",
            confirmation_status=confirmation, status="selected", reason="")])


def _result(*, fields, calculations=(), branches=(), uncertainties=(), confirmation: str | None = None,
            inputs: dict | None = None):
    return SettlementDecompositionResult(
        settlement_ref="settlement:T001",
        profile=DecompositionProfile(insurance_type="employee", medical_category="outpatient"),
        execution_status="complete",
        reconciliation_status="matched",
        fields=list(fields),
        branches=list(branches),
        calculations=list(calculations),
        uncertainties=list(uncertainties),
        coverage=CoverageSummary(
            target_field_count=len(fields), independently_explained_count=0,
            amount_reconciled_count=0, observed_only_count=0),
        answer_constraints=AnswerConstraints(may_claim_full_explanation=False),
        explanation_evidence=ExplanationEvidence(
            inputs=inputs or {}, rule_choices=[_group(confirmation)] if confirmation else [],
            settlement_date=date(2024, 4, 30)),
    )


def _view(result):
    return build_public_view_dict(result, summary_text="s", summary_source="template")


def test_conclusion_separates_reconciled_recalculated_and_confirmed():
    """金额相符 ≠ 依据已确认：当前口径重算与来源已核实必须分开表达。"""
    pending_input = FormulaInput(input_id="input-in", name="报销基数", value="100.00",
                                 status="verified", source="本笔结算记录")
    pending = _view(_result(fields=[_field("T_BigPay", "大额支付", ("calc.pay",))],
                            calculations=[_calc("calc.pay", operands=(CalculationOperandModel(
                                ref="fact.trade.in_scope", value="100.00", input_ref="input-in"),))],
                            confirmation="文档明确-待官方核证", inputs={"input-in": pending_input}))
    assert pending["fields"][0]["conclusion"] == "recalculated"
    assert "待确认" in pending["fields"][0]["conclusion_text"]

    # 依据已确认需要"重算输入已核实 + 采用规则来源已确认"同时成立。
    field_view = {"check_status": "matched", "explainable": True, "calculation_refs": ["calc.pay"]}
    calcs = {"calc.pay": {"verification_status": "verified", "rounding_rule": "精确到分", "operands": []}}
    groups = [_group("官方已核实")]
    assert _conclusion_of(field_view, calcs, groups)[0] == "basis_confirmed"
    assert _conclusion_of(field_view, {"calc.pay": {"verification_status": "unverified",
                                                    "rounding_rule": "精确到分", "operands": []}},
                          groups)[0] == "recalculated"

    reconciled = _view(_result(fields=[_field("T_BigPay", "大额支付")]))
    assert reconciled["fields"][0]["conclusion"] == "reconciled"
    assert "未独立重算" in reconciled["fields"][0]["conclusion_text"]

    book_only = _view(_result(fields=[_field("T_BigPay", "大额支付", check_status="not_applicable",
                                             observed_amount="0.00", calculated_amount=None,
                                             difference=None)]))
    assert book_only["fields"][0]["conclusion"] == "book_only"


def test_amount_semantics_declares_owner_and_comparability():
    """不同口径的金额不得相减：医院定额与患者待遇分开，恒等式只算账面关系。"""
    view = _view(_result(fields=[
        _field("QUOTA_AMOUNT", "医院核定定额", ("calc.fixed.hospital_fund",)),
        _field("T_BigPay", "大额支付", ("calc.pay",)),
        _field("T_SelfPay1", "自付一", check_type="identity_check"),
    ], calculations=[_calc("calc.pay"), _calc("calc.fixed.hospital_fund")]))
    fields = {item["field_code"]: item for item in view["fields"]}
    assert fields["QUOTA_AMOUNT"]["amount_semantics"]["owner"] == "hospital_settlement"
    assert fields["QUOTA_AMOUNT"]["amount_semantics"]["comparable"] is False
    assert fields["T_BigPay"]["amount_semantics"]["owner"] == "patient_benefit"
    assert fields["T_BigPay"]["amount_semantics"]["comparable"] is True
    assert fields["T_SelfPay1"]["amount_semantics"]["owner"] == "book_record"
    assert fields["T_SelfPay1"]["amount_semantics"]["comparable"] is False


def test_field_basis_traces_calculations_inputs_rules_and_sources():
    """来源列表之外，字段要能沿计算→输入→规则组→规则→来源标题追溯。"""
    calc = _calc("calc.pay", operands=(CalculationOperandModel(
        ref="fact.trade.in_scope", value="100.00", input_ref="input-in"),))
    view = _view(_result(fields=[_field("T_BigPay", "大额支付", ("calc.pay",))],
                         calculations=[calc], confirmation="官方已核实"))
    basis = view["fields"][0]["basis"]
    assert basis["calculation_ids"] == ["calc.pay"]
    assert len(basis["input_ids"]) == 1 and basis["input_ids"][0].startswith("input-")
    assert basis["rule_group_ids"] == ["rules-rate"]
    assert basis["rule_ids"] == ["EOP-RATE-1"]
    assert basis["source_titles"] == ["mz.docx §门诊大额"]


def test_global_gap_is_linked_to_affected_amounts():
    """全局缺口必须落到受影响金额；定位不到时标记 global，不能只在末尾笼统提示。"""
    view = _view(_result(
        fields=[_field("T_BigPay", "大额支付", ("calc.pay",)), _field("T_FeeAll", "总费用")],
        calculations=[_calc("calc.pay", rounding_rule="explicit:round_half_up(ESP-RND-001 待确认)")],
        uncertainties=[UncertaintyModel(id="u1", code="ROUNDING_RULE_PENDING_CONFIRMATION", message="m1"),
                       UncertaintyModel(id="u2", code="SOMETHING_GLOBAL", message="m2")]))
    gaps = {gap["code"]: gap for gap in view["uncertainties"]}
    assert gaps["ROUNDING_RULE_PENDING_CONFIRMATION"]["affected_fields"] == ["T_BigPay"]
    assert gaps["ROUNDING_RULE_PENDING_CONFIRMATION"]["scope"] == "field"
    assert gaps["SOMETHING_GLOBAL"]["affected_fields"] == []
    assert gaps["SOMETHING_GLOBAL"]["scope"] == "global"


def test_stage_completeness_reports_verified_premise_and_missing():
    """完整性按业务环节评价，不用字段数量代替。"""
    branch = BranchTraceModel(
        step_id="big_pay.rate_select", module_id="big_pay", outcome="true",
        condition=BranchConditionModel(code="big_pay_rate", description="大额基础支付比例档选择",
                                       operator="select", actual_value="70", expected_ref="EOP-RATE-1"),
        calculation_refs=["calc.pay"])
    uncertain = BranchTraceModel(
        step_id="big_pay.cap_check", module_id="big_pay", outcome="unknown",
        condition=BranchConditionModel(code="cap", description="基金支付封顶规则适用",
                                       operator="select", actual_value=None, expected_ref="候选"),
        calculation_refs=["calc.pay"])
    view = _view(_result(fields=[_field("T_BigPay", "大额支付", ("calc.pay",))],
                         calculations=[_calc("calc.pay", rounding_rule="explicit:round_half_up(ESP-RND-001 待确认)")],
                         branches=[branch, uncertain],
                         uncertainties=[UncertaintyModel(id="u1", code="ROUNDING_RULE_PENDING_CONFIRMATION",
                                                         message="m1")]))
    stages = {stage["stage_id"]: stage for stage in view["stages"]}
    fund = stages["fund"]
    assert fund["label"] == "统筹与大额"
    assert fund["status"] == "partial"
    assert any("大额基础支付比例档选择" in item for item in fund["verified"])
    assert any("基金支付封顶规则适用" in item for item in fund["premise"])
    assert "ROUNDING_RULE_PENDING_CONFIRMATION" in fund["missing"]


def test_trace_carries_versions_and_safe_evidence_id():
    """Issue #84 第 4 项：公开结果用安全编号关联审计侧完整轨迹，不暴露敏感原文。"""
    view = _view(_result(fields=[_field("T_BigPay", "大额支付", ("calc.pay",))],
                         calculations=[_calc("calc.pay")], confirmation="官方已核实"))
    trace = view["trace"]
    assert trace["algorithm_version"] == "employee_outpatient_v1"
    assert trace["rule_versions"] == ["2010"]
    assert trace["full_trace_in_public"] is False
    assert trace["evidence_id"].startswith("fee-evidence:")
    assert "settlement_ref" in trace


def test_confirmed_status_set_aligned_between_rule_inputs_and_conclusion():
    """rule_choices 输入验证与 public_view 结论分级共用同一确认集合：
    文档明确/官方已核实/已核实 判已确认；含"待"字状态两边都不放行。"""
    field_view = {"check_status": "matched", "explainable": True,
                  "calculation_refs": ["calc.pay"], "check_type": "independent_recalculation"}
    calcs = {"calc.pay": {"verification_status": "verified", "rounding_rule": "精确到分", "operands": []}}
    for confirmed_status in ("文档明确", "官方已核实", "已核实"):
        assert _conclusion_of(field_view, calcs, [_group(confirmed_status)])[0] == "basis_confirmed", confirmed_status
    for pending_status in ("文档明确-待官方核证", "待确认", "实测待码表确认", "用户补充规则，待业务签核"):
        assert _conclusion_of(field_view, calcs, [_group(pending_status)])[0] == "recalculated", pending_status
