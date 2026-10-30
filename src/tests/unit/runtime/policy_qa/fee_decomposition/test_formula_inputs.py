"""公式输入的身份、信任状态及同日候选边界。"""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from src.runtime.policy_qa.fee_decomposition.explanation_evidence import (
    ExplanationEvidence, FormulaInput, attach_evidence, input_id,
)
from src.runtime.policy_qa.fee_decomposition.employee_outpatient import decompose_employee_outpatient
from src.runtime.policy_qa.fee_decomposition.public_view import build_public_view_dict, to_public_contract_dict
from src.runtime.policy_qa.fee_decomposition.result import CalculationOperandModel, CalculationRecordModel
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_public_explanation import _result
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_employee_outpatient import _snapshot
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_special_mz_golden import _snapshot_djh567
from src.runtime.policy_qa.fee_decomposition.employee_outpatient_special import decompose_employee_outpatient_special


def calc(ident, refs, value="10"):
    return CalculationRecordModel(calculation_id=ident, formula_id="catalog_total_fee_v1", formula_version="v1",
                                  operands=[CalculationOperandModel(ref=ref, value=value) for ref in refs], result=value)


def view(result):
    return build_public_view_dict(result, summary_text="", summary_source="template")


def test_verified_leaf_links_recursively_and_same_value_does_not_merge_identity():
    result = _result(calculations=[calc("calc.a", ["fact.one"]), calc("calc.b", ["calc.a", "fact.two"])])
    result.explanation_evidence = ExplanationEvidence(settlement_date=date(2024, 1, 1), inputs={
        ref: FormulaInput(input_id=input_id(ref), name="原始输入一" if ref == "fact.one" else "原始输入二", value="10", status="verified", source="原始记录")
        for ref in ("fact.one", "fact.two")})
    public = view(result)
    assert all(c["verification_status"] == "verified" for c in public["calculations"])
    assert len(public["formula_inputs"]) == 3
    assert public["calculations"][1]["operands"][0]["calculation_ref"] == "calc.a"
    assert "fact.one" not in str(public["calculations"])
    assert "原始输入一" in public["calculations"][0]["formula"]


def test_unverified_leaf_blocks_downstream_even_when_amounts_match():
    public = view(_result(calculations=[calc("calc.a", ["fact.unproven"]), calc("calc.b", ["calc.a"])]))
    assert [c["verification_status"] for c in public["calculations"]] == ["unverified", "unverified"]
    assert next(i for i in public["formula_inputs"] if i["calculation_ref"] == "calc.a")["status"] == "unverified"


def test_unverified_calculation_cannot_claim_full_public_explanation():
    result = _result(calculations=[calc("calc.a", ["fact.unproven"])])
    result.answer_constraints.may_claim_full_explanation = True
    public = build_public_view_dict(result, summary_text="费用分解完整解释。", summary_source="template")
    assert public["may_claim_full_explanation"] is False
    assert "完整解释" not in public["summary_text"]


def test_cycles_and_inconsistent_references_are_conflicts():
    public = view(_result(calculations=[calc("calc.a", ["calc.b"]), calc("calc.b", ["calc.a"])]))
    assert all(c["verification_status"] == "conflict" for c in public["calculations"])
    public = view(_result(calculations=[calc("calc.a", ["fact.one"], "10"), calc("calc.b", ["calc.a"], "11")]))
    assert public["calculations"][1]["verification_status"] == "conflict"


def test_input_sign_mismatch_cannot_be_hidden_by_equal_magnitude():
    result = _result(calculations=[CalculationRecordModel(calculation_id="calc.product", formula_id="retire_supplement_v1", formula_version="v1",
        operands=[CalculationOperandModel(ref="fact.one", value="-10")], result="-10")])
    result.explanation_evidence = ExplanationEvidence(settlement_date=date(2024, 1, 1), inputs={
        "fact.one": FormulaInput(input_id=input_id("fact.one"), name="原始基数", value="10", source="费用明细", status="verified")})
    assert view(result)["calculations"][0]["verification_status"] == "conflict"


def test_candidate_table_uses_settlement_date_and_does_not_include_display_only_rates():
    snapshot = _snapshot()
    result = attach_evidence(decompose_employee_outpatient(snapshot), snapshot)
    public = view(result)
    rows = [row for group in public["rule_choices"] for row in group["candidates"]]
    rates = [row for row in rows if row["rule_id"].startswith("EOP-RATE-")]
    assert any(row["status"] == "selected" for row in rates)
    assert any(row["status"] == "excluded" for row in rates)
    assert all(row["rule_id"] not in ("EOP-RATE-201", "EOP-RATE-202", "EOP-RATE-203", "EOP-RATE-303") for row in rates)
    assert all(row["effective_to"] == "尚未终止" or row["effective_to"] >= "2024-06-01" for row in rows if row["effective_to"] is not None)
    retired = [row for row in rates if any(check["expected"] == "退休" for check in row["checks"])]
    assert all(row["status"] == "excluded" for row in retired)
    assert all(check["outcome"] == "unknown" for row in retired for check in row["checks"] if check["name"] == "年龄档")
    historical = replace(snapshot, trade=replace(snapshot.trade, trade_date=date(2007, 1, 1)))
    old = attach_evidence(decompose_employee_outpatient(historical), historical)
    old_rows = [row for group in view(old)["rule_choices"] for row in group["candidates"]]
    assert any(row["rule_id"] == "EOP-DED-001" for row in old_rows)
    assert not any(row["rule_id"] == "EOP-DED-002" for row in old_rows)


def test_evidence_is_transient_and_new_text_leaves_are_sanitized():
    snapshot = _snapshot()
    result = attach_evidence(decompose_employee_outpatient(snapshot), snapshot)
    assert "explanation_evidence" not in result.model_dump()
    assert result.explanation_evidence
    result.explanation_evidence.inputs["fact.trade.prior_fund_payment"].source = "SENSITIVE"
    result.explanation_evidence.rule_choices[0].candidates[0].checks[0].expected = "SENSITIVE"
    public = to_public_contract_dict(result, summary_text="", summary_source="template", sanitize=lambda text: str(text).replace("SENSITIVE", "已脱敏"))
    assert "SENSITIVE" not in str(public)


def test_special_retired_ratio_and_segment_base_have_real_upstream_calculations():
    snapshot = _snapshot_djh567()
    result = attach_evidence(decompose_employee_outpatient_special(snapshot), snapshot)
    index = {c.calculation_id: c for c in result.calculations}
    assert index["calc.deductible.copay_base"].result == "4700.00"
    segment = index["calc.pool.segment.ESP-RATE-101.base"]
    assert segment.result == "4700.00"
    ratio = index["calc.pool.segment.ESP-RATE-101.self_ratio"]
    assert Decimal(ratio.result) == Decimal("0.09")
    assert [(o.ref, Decimal(o.value)) for o in ratio.operands][:2] == [("rule.ESP-RATE-101", Decimal("0.15")), ("rule.ESP-RATE-113", Decimal("0.60"))]
    assert index["calc.pool.segmented"].result == "4277.00"
    choices = next(group for group in result.explanation_evidence.rule_choices if group.group_id == "rules-ESP-RATE")
    unused = next(row for row in choices.candidates if row.rule_id == "ESP-RATE-102")
    assert unused.status == "excluded"
    assert any(check.actual and check.actual.startswith("本笔与此段交集 0") for check in unused.checks)
    assert all(o.ref.startswith("calc.pool.segment.") for o in index["calc.pool.segmented"].operands if o.ref.endswith("self_ratio"))
    changed = replace(snapshot, observed=replace(snapshot.observed, tczhf=Decimal("1")))
    other = attach_evidence(decompose_employee_outpatient_special(changed), changed)
    assert result.explanation_evidence.rule_choices == other.explanation_evidence.rule_choices
    assert next(c for c in other.calculations if c.calculation_id == "calc.pool.segmented").result == "4277.00"


def test_resident_candidates_and_secondary_identity_are_separate_from_employee_rates():
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_resident_outpatient import _snapshot as outpatient
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_resident_outpatient_special import _snapshot as special, _split
    from src.runtime.policy_qa.fee_decomposition.resident_outpatient import decompose_resident_outpatient
    from src.runtime.policy_qa.fee_decomposition.resident_outpatient_special import decompose_resident_outpatient_special
    snapshot = outpatient()
    ordinary = view(attach_evidence(decompose_resident_outpatient(snapshot), snapshot))
    assert any(group["group_id"] == "rules-ROP-RATE" for group in ordinary["rule_choices"])
    assert not any(group["group_id"].startswith("rules-EOP-") for group in ordinary["rule_choices"])
    snapshot = special()
    result = view(attach_evidence(decompose_resident_outpatient_special(snapshot, _split()), snapshot))
    rates = next(group for group in result["rule_choices"] if group["group_id"] == "rules-RSP-RATE")
    assert len(rates["candidates"]) == 3
    assert sum(row["status"] == "selected" for row in rates["candidates"]) == 1
    db = next(group for group in result["rule_choices"] if group["group_id"] == "rules-secondary-db")
    assert len(db["candidates"]) == 4
    assert {row["value"] for row in db["candidates"]} == {"60.00", "65.00", "70.00", "75.00"}
    aid = next(group for group in result["rule_choices"] if group["group_id"] == "rules-secondary-aid")
    assert len(aid["candidates"]) == 5


def test_rule_group_title_omits_not_applicable_payment_level():
    # payment_level="不适用" 的参数语义是"无支付层次"，兜底标题只用 category，
    # 不得拼出"起付线 · 不适用"（读起来像本单起付规则不适用）。
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_resident_outpatient import _snapshot as outpatient
    from src.runtime.policy_qa.fee_decomposition.resident_outpatient import decompose_resident_outpatient

    snapshot = outpatient()
    ordinary = view(attach_evidence(decompose_resident_outpatient(snapshot), snapshot))
    titles = {group["group_id"]: group["title"] for group in ordinary["rule_choices"]}
    assert "rules-ROP-DED" in titles and "rules-ROP-CAP" in titles
    assert titles["rules-ROP-DED"] == "起付线"
    assert titles["rules-ROP-CAP"] == "封顶线"
    assert all("不适用" not in title for title in titles.values())

    snapshot = _snapshot()
    employee = view(attach_evidence(decompose_employee_outpatient(snapshot), snapshot))
    emp_titles = {group["group_id"]: group["title"] for group in employee["rule_choices"]}
    assert "rules-EOP-DED" in emp_titles
    assert emp_titles["rules-EOP-DED"] == "起付线"
    assert all("不适用" not in title for title in emp_titles.values())


def test_xjzf_identity_zero_subtrahends_render_minus_sign():
    # XJZF 账面恒等：零值减项取负后不得丢符号（-Decimal("0.00") 在十进制上下文中丢符号，
    # 构造分量必须用 copy_negate），否则公开公式把减项渲染成加号（"＋ 大额互助支付 0.00"）。
    snapshot = _snapshot_djh567()
    result = view(attach_evidence(decompose_employee_outpatient_special(snapshot), snapshot))
    calc = next(c for c in result["calculations"]
                if c["calculation_id"] == "calc.identity.xjzf_channel")
    operand = next(o for o in calc["operands"] if o["display_name"] == "大额互助支付")
    assert operand["value"] == "-0.00"
    assert "＋ 大额互助支付" not in calc["formula"]
    assert "－ 大额互助支付 0.00" in calc["formula"]


def test_retired_age_has_an_actual_formula_without_exposing_birth_date():
    snapshot = _snapshot(person_code="21")
    snapshot = replace(snapshot, person=replace(snapshot.person, birth_date=date(1960, 6, 2)))
    result = view(attach_evidence(decompose_employee_outpatient(snapshot), snapshot))
    age = next(c for c in result["calculations"] if c["calculation_id"] == "calc.age.full_years")
    assert age["result"] == "63"
    assert "年份差 64" in age["formula"] and "未到扣减 1" in age["formula"]
    assert age["verification_status"] == "verified"
    assert "1960-06-02" not in str(result)
    node = next(i for i in result["formula_inputs"] if i["name"] == "结算日已满周岁")
    assert node["calculation_ref"] == "calc.age.full_years"


def test_ordinary_fund_segments_record_each_base_and_payment():
    snapshot = _snapshot()
    result = attach_evidence(decompose_employee_outpatient(snapshot), snapshot)
    index = {c.calculation_id: c for c in result.calculations}
    assert Decimal(index["calc.big_pay.segment.base.base"].result) == Decimal("1200")
    assert Decimal(index["calc.big_pay.segment.excess_20k.base"].result) == 0
    assert Decimal(index["calc.big_pay.segment.base.pay"].result) == Decimal("840")
    group = next(g for g in result.explanation_evidence.rule_choices if g.group_id == "rules-EOP-RATE")
    assert all(row.status == "excluded" for row in group.candidates if row.rule_id in ("EOP-RATE-301", "EOP-RATE-302"))
