"""费用分解公开视图与确定性模板渲染单元测试（Issue #78 设计 §11/§12）。

覆盖：
- 模板渲染：complete/partial/unavailable 三状态措辞；matched/mismatched/
  not_verifiable/not_applicable 四核对状态措辞；差异原样呈现不判定对错；
- 公开视图映射：金额十进制字符串透传、覆盖统计、answer_constraints 透传；
- 审计级细节（分支轨迹/计算记录/快照引用）不进入公开视图。
"""
from __future__ import annotations

from src.runtime.policy_qa.fee_decomposition.public_view import (
    build_public_view_dict,
    render_summary,
)
from src.runtime.policy_qa.fee_decomposition.result import (
    AnswerConstraints,
    BranchTraceModel,
    CoverageSummary,
    DecompositionProfile,
    FieldExplanationModel,
    SettlementDecompositionResult,
    UncertaintyModel,
)


def _field(**overrides) -> FieldExplanationModel:
    base = dict(
        field_code="T_BigPay",
        label="大额支付",
        check_type="independent_recalculation",
        check_status="matched",
        observed_amount="60.00",
        calculated_amount="60.00",
        difference="0.00",
        explanation_level="causally_explained",
    )
    return FieldExplanationModel(**(base | overrides))


def _result(
    *,
    execution_status: str = "complete",
    reconciliation_status: str = "matched",
    fields: list[FieldExplanationModel] | None = None,
    uncertainties: list[UncertaintyModel] | None = None,
    may_claim_full: bool = True,
) -> SettlementDecompositionResult:
    return SettlementDecompositionResult(
        settlement_ref="settlement:T001",
        profile=DecompositionProfile(insurance_type="employee", medical_category="outpatient"),
        execution_status=execution_status,
        reconciliation_status=reconciliation_status,
        fields=fields or [],
        uncertainties=uncertainties or [],
        coverage=CoverageSummary(
            target_field_count=len(fields or []),
            independently_explained_count=0,
            amount_reconciled_count=0,
            observed_only_count=0,
        ),
        answer_constraints=AnswerConstraints(may_claim_full_explanation=may_claim_full),
    )


class TestRenderSummary:
    def test_complete_matched(self):
        text = render_summary(_result(fields=[_field()]))
        assert "完整解释" in text
        assert "核对一致" in text
        assert "大额支付：结算记录 60.00 元，按规则重算 60.00 元，一致。" in text

    def test_partial_wording(self):
        text = render_summary(_result(
            execution_status="partial", reconciliation_status="not_verifiable",
            fields=[_field()], may_claim_full=False))
        assert "部分解释" in text
        assert "暂不能核对" in text
        assert "完整解释" not in text

    def test_mismatched_presents_difference_without_judgement(self):
        text = render_summary(_result(
            reconciliation_status="mismatched",
            fields=[_field(check_status="mismatched", calculated_amount="59.00",
                           difference="-1.00", explanation_level="observed_only")],
        ))
        assert "差额 -1.00 元" in text
        assert "不判定对错" in text
        assert "存在差异" in text

    def test_not_verifiable_variants(self):
        text = render_summary(_result(
            execution_status="partial", reconciliation_status="not_verifiable",
            fields=[
                _field(check_status="not_verifiable", difference=None,
                       explanation_level="observed_only"),
                _field(field_code="T_BCPay", label="退休补充保险补助",
                       check_status="not_verifiable", calculated_amount=None,
                       difference=None, explanation_level="observed_only"),
            ],
            may_claim_full=False,
        ))
        assert "暂不能与账面核对" in text
        assert "退休补充保险补助：结算记录 60.00 元，暂不能独立计算。" in text

    def test_not_applicable(self):
        text = render_summary(_result(fields=[_field(
            check_status="not_applicable", calculated_amount=None, difference=None,
            explanation_level="unexplained")]))
        assert "大额支付：本单不适用。" in text

    def test_observed_missing(self):
        text = render_summary(_result(fields=[_field(
            check_status="not_verifiable", observed_amount=None,
            calculated_amount=None, difference=None,
            explanation_level="unexplained")]))
        assert "结算记录缺失" in text

    def test_unavailable_without_fields_lists_uncertainties(self):
        text = render_summary(_result(
            execution_status="unavailable", reconciliation_status="not_verifiable",
            fields=[],
            uncertainties=[UncertaintyModel(
                id="u.flow.unsupported_profile", code="UNSUPPORTED_PROFILE",
                message="首期仅支持城镇职工×普通门诊。")],
            may_claim_full=False,
        ))
        assert "暂不可用" in text
        assert "未决事项：首期仅支持城镇职工×普通门诊。" in text

    def test_uncertainties_appended(self):
        text = render_summary(_result(
            fields=[_field()],
            uncertainties=[UncertaintyModel(
                id="u.rounding.rule", code="ROUNDING_RULE_PENDING_CONFIRMATION",
                message="取整规则待确认。")],
        ))
        assert "未决事项：取整规则待确认。" in text

    def test_uncertainties_deduplicated_by_message(self):
        # 同一未决文案多来源命中（仅 id 不同）时，未决事项只保留一次，保序
        text = render_summary(_result(
            fields=[_field()],
            uncertainties=[
                UncertaintyModel(id="u.a", code="C", message="目录划分语义待确认。"),
                UncertaintyModel(id="u.b", code="C", message="取整规则待确认。"),
                UncertaintyModel(id="u.c", code="C", message="目录划分语义待确认。"),
            ],
        ))
        assert "未决事项：目录划分语义待确认。；取整规则待确认。" in text
        assert text.count("目录划分语义待确认。") == 1


class TestBuildPublicViewDict:
    def test_mapping_and_amount_passthrough(self):
        result = _result(fields=[_field()], uncertainties=[UncertaintyModel(
            id="u1", code="C1", message="m1")])
        view = build_public_view_dict(result, summary_text="s", summary_source="template")
        # 公开投影独立标识 1.10（内部结果 schema_version 保持 1.0）
        assert result.schema_version == "1.0"
        assert view["schema_version"] == "1.10"
        assert view["algorithm_version"] == "employee_outpatient_v1"
        assert view["execution_status"] == "complete"
        assert view["reconciliation_status"] == "matched"
        assert view["may_claim_full_explanation"] is False  # 未返回独立计算记录，金额一致仍不构成完整解释。
        assert view["summary_text"] == "s"
        assert view["summary_source"] == "template"
        assert view["fields"][0]["observed_amount"] == "60.00"
        assert view["fields"][0]["calculated_amount"] == "60.00"
        assert view["uncertainties"] == [
            {"code": "C1", "message": "m1", "id": "u1", "affected_fields": [], "scope": "global"}]
        assert view["coverage"]["target_field_count"] == 1
        # 解释投影 1.1 顶层数组：无数据时为空
        assert view["calculations"] == []
        assert view["sources"] == []
        assert view["conditions"] == []

    def test_self_pay_1_identity_keeps_zero_subtraction_sign(self):
        from src.runtime.policy_qa.fee_decomposition.result import (
            CalculationOperandModel, CalculationRecordModel)

        for public_pay, total in (("0.00", "1980.00"), ("-20.00", "1960.00")):
            result = _result(fields=[
                _field(field_code="T_SelfPay1", label="个人支付自付（一）金额",
                       check_type="identity_check", observed_amount=total,
                       calculated_amount=total, calculation_refs=["calc.identity.self_pay_1"]),
                _field(field_code="T_FeeIn", label="医保内费用"),
                _field(field_code="T_BigPay", label="大额支付"),
                _field(field_code="T_OfficalPay", label="公疗补充支付"),
            ])
            result.calculations = [CalculationRecordModel(
                calculation_id="calc.identity.self_pay_1",
                formula_id="identity_self_pay_1_v1", formula_version="v1",
                operands=[
                    CalculationOperandModel(ref="T_FeeIn", value="2400.00"),
                    CalculationOperandModel(ref="T_BigPay", value="-420.00"),
                    CalculationOperandModel(ref="T_OfficalPay", value=public_pay),
                ], result=total)]
            view = build_public_view_dict(result, summary_text="", summary_source="template")
            formula = view["calculations"][0]["formula"]
            assert "＋ 公疗补充支付" not in formula
            assert f"－ 公疗补充支付 {public_pay.lstrip('-')}" in formula

    def test_field_brief_no_duplicate_benci_prefix(self):
        # 内部 label 已以"本次"开头（如 T_FirstPay="本次起付承担"）时，brief 不再叠加前缀。
        # 直测 _field_brief：build_public_view_dict 下游会按 explainable 重投影 brief。
        from src.runtime.policy_qa.fee_decomposition.public_view import _field_brief

        calc_view = {
            "calculation_id": "calc.deductible.observed",
            "display_name": "起付线（按结算记录）",
            "formula": None,
            "result": "1300.00",
            "layout": "generic",
            "operands": [{"display_name": "结算记录数据项", "value": "1300.00"}],
        }
        brief = _field_brief(
            _field(field_code="T_FirstPay", label="本次起付承担",
                   calculation_refs=["calc.deductible.observed"]),
            ["calc.deductible.observed"], {"calc.deductible.observed": calc_view})
        assert brief is not None
        assert "本次本次" not in brief
        assert brief.startswith("本次起付承担按")
        # 对照：label 不含"本次"时仍加前缀
        brief_plain = _field_brief(
            _field(field_code="T_BigPay", label="大额支付",
                   calculation_refs=["calc.deductible.observed"]),
            ["calc.deductible.observed"], {"calc.deductible.observed": calc_view})
        assert brief_plain is not None
        assert brief_plain.startswith("本次大额支付按")

    def test_audit_details_excluded(self):
        result = _result(fields=[_field()])
        result.branches.append(BranchTraceModel(step_id="s", module_id="m", outcome="true"))
        view = build_public_view_dict(result, summary_text="", summary_source="template")
        # 审计级原始结构不公开；公开的是投影后的 calculations/sources/conditions 视图
        assert "branches" not in view
        assert "citations" not in view
        assert "settlement_ref" not in view
        assert "profile" not in view
        assert "answer_constraints" not in view
        # 无条件的分支（condition=None）不产生公开条件
        assert view["conditions"] == []


class TestModuleLabelsCoverage:
    def test_module_labels_cover_all_kernel_module_ids(self):
        # 内核分支实际使用的 module_id 必须全部有业务名，不回落"其他计算步骤"
        import re
        from pathlib import Path

        from src.runtime.policy_qa.fee_decomposition import public_view

        kernel = Path(__file__).parents[5] / "runtime" / "policy_qa" / "fee_decomposition"
        ids: set[str] = set()
        for path in kernel.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            ids.update(re.findall(r'module_id="([a-z_0-9]+)"', text))
            ids.update(re.findall(r'(?:_?MODULE_ID|\bmid|\bmodule)\s*=\s*"([a-z_0-9]+)"', text))
            # 位置参数形式：BranchTrace("step", "module", ...)
            ids.update(re.findall(r'BranchTrace\(\s*"[^"]+",\s*"([a-z_0-9]+)"', text))
        ids.discard("")
        missing = ids - set(public_view._MODULE_LABELS)
        assert not missing, f"未映射的内核模块: {sorted(missing)}"


# ── 评审问题 3：多步骤字段直接给出真实公式与上游基数 ──────────────────


def _calc_model(cid, fid, pairs, result):
    from src.runtime.policy_qa.fee_decomposition.result import (
        CalculationOperandModel, CalculationRecordModel)
    return CalculationRecordModel(
        calculation_id=cid, formula_id=fid, formula_version="v1",
        operands=[CalculationOperandModel(ref=ref, value=value) for ref, value in pairs],
        result=result)


def test_multi_step_field_brief_renders_terminal_formula_and_upstream_bases():
    """多步骤字段 brief：终端公式 + 沿 calculation_ref 选取的上游基数；不再用占位说明。"""
    result = _result(fields=[_field(
        field_code="T_BigPay", label="大额支付", observed_amount="1597.50",
        calculated_amount="1597.50", calculation_refs=["calc.big_pay.capped"])]
    ).model_copy(update={
        "algorithm_version": "resident_outpatient_v1",
        "calculations": [
            _calc_model("calc.big_pay.cap_room", "cap_room_v1",
                        [("rule.cap", "4500"), ("input.prior_paid", "2304.50")], "2195.50"),
            _calc_model("calc.big_pay.capped", "resident_big_pay_clamp_v1",
                        [("input.base", "3195.00"), ("rule.rate", "0.5"),
                         ("input.prior_paid", "2304.50"), ("rule.cap", "4500"),
                         ("calc.big_pay.cap_room", "2195.50")], "1597.50"),
        ],
    })
    view = build_public_view_dict(result, summary_text="", summary_source="template")
    brief = view["fields"][0]["brief"]
    assert brief
    assert "个计算步骤得出" not in brief
    assert "可展开查看" not in brief
    # 终端公式（真实代入）
    assert "取整（基数 3195.00 元×比例 0.5）" in brief
    assert "1597.50" in brief
    # 上游基数：封顶余额＝封顶 4500－交易前已支付 2304.50＝2195.50（剩余额度的作用）
    assert "2195.50" in brief
    assert "4500" in brief and "2304.50" in brief
    # 同源：字段固定说明的构成即同一份文字（面板与聊天一致）
    explanation = view["fields"][0]["explanation"]
    assert explanation is not None
    assert "取整（基数 3195.00 元×比例 0.5）" in (explanation["composition"] or "")


def test_resident_deductible_interval_formula_states_covered_standard():
    """交易前累计已覆盖起付标准时，起付 0 的公式直接说明覆盖关系（0408：5159≥550）。"""
    from src.runtime.policy_qa.fee_decomposition.formula_text import calculation_formula
    calc = _calc_model("calc.deductible.split", "resident_deductible_interval_v1",
                       [("input.fee", "3195.00"), ("input.prior", "5159.00"),
                        ("rule.standard", "550")], "0.00")
    text = calculation_formula(calc, [])
    assert text
    assert "5159.00" in text
    assert "550" in text
    assert "已达到起付标准" in text
    # 未覆盖场景保持原区间口径（部分起付 100）
    partial = _calc_model("calc.deductible.split", "resident_deductible_interval_v1",
                          [("input.fee", "3195.00"), ("input.prior", "450.00"),
                           ("rule.standard", "550")], "100.00")
    text_partial = calculation_formula(partial, [])
    assert "累计区间" in text_partial


# ── 评审问题 8：bill.* 缺口说明由实际输入状态决定 ────────────────────


def test_beyond_cap_boundary_reflects_existing_cap_and_prior_inputs():
    """已有封顶标准与交易前累计输入时，不得仍写"缺封顶规则与累计"。"""
    from datetime import date as _date
    from src.runtime.policy_qa.fee_decomposition.explanation_evidence import (
        ExplanationEvidence, FormulaInput, RuleCandidate, RuleChoiceGroup, input_id)
    from src.runtime.policy_qa.fee_decomposition.settlement_facts import (
        SettlementDisplayField, SettlementDisplayView, SettlementFactsView)
    result = _result(fields=[_field()]).model_copy(update={
        "algorithm_version": "resident_outpatient_v1",
        "calculations": [
            _calc_model("calc.big_pay.capped", "resident_big_pay_clamp_v1",
                        [("input.base", "3195.00"), ("rule.rate", "0.5")], "1597.50"),
        ],
        "explanation_evidence": ExplanationEvidence(
            settlement_date=_date(2024, 4, 8),
            inputs={"input.prior": FormulaInput(
                input_id=input_id("input.prior"), name="交易前年度累计",
                value="2304.50", status="verified", source="年度累计快照")},
            rule_choices=[RuleChoiceGroup(
                group_id="rules-ROP-CAP", title="封顶线",
                calculation_refs=["calc.big_pay.capped"], field_refs=["T_BigPay"],
                input_refs=[input_id("input.prior")],
                candidates=[RuleCandidate(
                    rule_id="ROP-CAP-003", name="门诊基金年度最高支付限额",
                    value="4500", unit="元/保险年度", version="V2021-01-01",
                    source="居民门诊待遇参数表", confirmation_status="文档明确-待官方核证",
                    status="selected", reason="", checks=[])])]),
    })
    facts = SettlementFactsView(
        chain="outpatient",
        display_template=SettlementDisplayView(
            template_id="resident_outpatient", version="1.0", title="居民门诊结算单",
            layout_status="provisional",
            fields=[
                SettlementDisplayField(
                    key="big_pay", label="大额支付", section="transaction",
                    row=1, column=1, scope="patient_actual", value="1597.50",
                    field_code="T_BigPay", source_kind="record", status="available"),
                SettlementDisplayField(
                    key="beyond_cap", label="大额超封顶金额", section="transaction",
                    row=1, column=2, scope="patient_actual", value="0.00",
                    field_code=None, source_kind="unmapped", status="unmapped"),
            ]))
    view = build_public_view_dict(
        result, summary_text="", summary_source="template", settlement_facts=facts)
    boundary = view["template_explanations"]["beyond_cap"]["boundary"] or ""
    assert "缺大额封顶规则与本笔交易前累计" not in boundary
    assert "已有大额封顶标准与交易前累计输入" in boundary
    assert "归属未经确认" in boundary


def test_beyond_cap_boundary_without_inputs_stays_generic_and_honest():
    """无封顶/累计输入时：不写死缺什么，只声明无独立计算/归属映射。"""
    from src.runtime.policy_qa.fee_decomposition.settlement_facts import (
        SettlementDisplayField, SettlementDisplayView, SettlementFactsView)
    result = _result(fields=[_field()]).model_copy(update={
        "algorithm_version": "resident_outpatient_v1"})
    facts = SettlementFactsView(
        chain="outpatient",
        display_template=SettlementDisplayView(
            template_id="resident_outpatient", version="1.0", title="居民门诊结算单",
            layout_status="provisional",
            fields=[SettlementDisplayField(
                key="beyond_cap", label="大额超封顶金额", section="transaction",
                row=1, column=2, scope="patient_actual", value=None,
                field_code=None, source_kind="unmapped", status="unmapped")]))
    view = build_public_view_dict(
        result, summary_text="", summary_source="template", settlement_facts=facts)
    boundary = view["template_explanations"]["beyond_cap"]["boundary"] or ""
    assert "缺大额封顶规则与本笔交易前累计" not in boundary
    assert "无独立计算或费用归属映射" in boundary
