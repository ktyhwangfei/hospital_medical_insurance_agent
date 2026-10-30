"""解释投影 1.1 单元测试（2026-10-15 费用解释改造切片 1）。

覆盖：
- 公开边界：快照物理路径/本地路径/无效协议链接不透传；issue_note、source_catalog
  不进入公开来源；数组 values 逐项过消毒边界；
- 关系正确性：字段引用只指向存在的计算/来源/缺口；重复冲突 ID 整体剔除；
  缺失引用只降级受影响字段；condition 为空合法；
- 状态与金额：零值、负差异、not_applicable、approval_status=pending 均不升级；
- 确定性简述 brief：恒等式账面勾稽措辞、单计算构成说明、缺口说明；
- to_public_contract_dict：全部公开字符串叶（含数组）都经过 sanitize。
"""
from __future__ import annotations

from src.runtime.policy_qa.fee_decomposition.public_view import (
    PUBLIC_SCHEMA_VERSION,
    build_public_view_dict,
    to_public_contract_dict,
)
from src.runtime.policy_qa.fee_decomposition.result import (
    AnswerConstraints,
    BranchConditionModel,
    BranchTraceModel,
    CalculationOperandModel,
    CalculationRecordModel,
    CitationModel,
    CoverageSummary,
    DecompositionProfile,
    FieldExplanationModel,
    SettlementDecompositionResult,
    UncertaintyModel,
)


def _result(
    *,
    fields: list[FieldExplanationModel] | None = None,
    branches: list[BranchTraceModel] | None = None,
    calculations: list[CalculationRecordModel] | None = None,
    citations: list[CitationModel] | None = None,
    uncertainties: list[UncertaintyModel] | None = None,
) -> SettlementDecompositionResult:
    return SettlementDecompositionResult(
        settlement_ref="settlement:T001",
        profile=DecompositionProfile(insurance_type="employee", medical_category="outpatient"),
        execution_status="complete",
        reconciliation_status="matched",
        fields=fields or [],
        branches=branches or [],
        calculations=calculations or [],
        citations=citations or [],
        uncertainties=uncertainties or [],
        coverage=CoverageSummary(
            target_field_count=len(fields or []),
            independently_explained_count=0,
            amount_reconciled_count=0,
            observed_only_count=0,
        ),
        answer_constraints=AnswerConstraints(may_claim_full_explanation=False),
    )


def _field(**overrides) -> FieldExplanationModel:
    base = dict(
        field_code="T_SelfPayAll",
        label="最终个人承担",
        check_type="identity_check",
        check_status="matched",
        observed_amount="68.85",
        calculated_amount="68.85",
        difference="0.00",
        explanation_level="amount_reconciled",
    )
    return FieldExplanationModel(**(base | overrides))


def _calc(**overrides) -> CalculationRecordModel:
    base = dict(
        calculation_id="calc.identity.self_pay_all",
        formula_id="identity_self_pay_all_v1",
        formula_version="v1",
        operands=(
            CalculationOperandModel(ref="T_FirstPay", value="100.00"),
            CalculationOperandModel(ref="T_BCPay", value="-7.70"),
        ),
        unrounded_result="92.30",
        rounding_rule="not_applicable（账面分量加减，无取整）",
        result="92.30",
    )
    return CalculationRecordModel(**(base | overrides))


def _view(result) -> dict:
    return build_public_view_dict(result, summary_text="", summary_source="template")


class TestVersionAndRefResolution:
    def test_public_schema_version_is_1_1(self):
        assert PUBLIC_SCHEMA_VERSION == "1.10"
        assert _view(_result())["schema_version"] == "1.10"

    def test_field_refs_resolve_to_public_arrays(self):
        result = _result(
            fields=[_field(
                calculation_refs=["calc.identity.self_pay_all"],
                citation_refs=["fact.trade.trade_date"],
                uncertainty_refs=["u.rounding"],
            )],
            calculations=[_calc()],
            citations=[CitationModel(
                id="fact.trade.trade_date", kind="settlement_fact",
                ref="snapshot:settlement:T001/trade/T_TradeDate", value="2026-09-01")],
            uncertainties=[UncertaintyModel(
                id="u.rounding", code="ROUNDING_RULE_PENDING_CONFIRMATION",
                message="取整规则待确认。", affected_fields=["T_SelfPayAll"])],
        )
        view = _view(result)
        field = view["fields"][0]
        assert field["calculation_refs"] == ["calc.identity.self_pay_all"]
        assert field["source_refs"] == ["fact.trade.trade_date"]
        assert field["gap_refs"] == ["u.rounding"]
        assert view["calculations"][0]["calculation_id"] == "calc.identity.self_pay_all"
        assert view["uncertainties"][0]["affected_fields"] == ["T_SelfPayAll"]

    def test_missing_refs_degrade_only_explanation(self):
        result = _result(fields=[_field(
            calculation_refs=["calc.nonexistent"],
            citation_refs=["fact.nonexistent"],
            uncertainty_refs=["u.nonexistent"],
        )])
        view = _view(result)
        field = view["fields"][0]
        # 金额保留，引用清空，brief 说明未记录
        assert field["observed_amount"] == "68.85"
        assert field["calculation_refs"] == []
        assert field["source_refs"] == []
        assert field["gap_refs"] == []
        assert field["brief"] is None
        assert not field["explainable"]

    def test_conflicting_duplicate_ids_dropped(self):
        duplicate = CitationModel(
            id="rule.x", kind="policy_document", ref="https://a.example/x", value="X")
        conflicting = CitationModel(
            id="rule.x", kind="policy_document", ref="https://b.example/y", value="Y")
        result = _result(
            fields=[_field(citation_refs=["rule.x"])],
            citations=[duplicate, conflicting],
        )
        view = _view(result)
        # 关联歧义：不任取一条，来源与引用都剔除
        assert view["sources"] == []
        assert view["fields"][0]["source_refs"] == []

    def test_identical_duplicate_ids_merged(self):
        citation = CitationModel(
            id="fact.a", kind="settlement_fact", ref="snapshot:s/a", value="1")
        result = _result(citations=[citation, citation.model_copy()])
        view = _view(result)
        assert len(view["sources"]) == 1


class TestSourceSafety:
    def test_settlement_fact_hides_snapshot_ref_and_link(self):
        result = _result(citations=[CitationModel(
            id="fact.trade.person_type_code", kind="settlement_fact",
            ref="snapshot:settlement:T001/trade/PN_PersonType", value="11")])
        source = _view(result)["sources"][0]
        assert source["category"] == "settlement_record"
        assert source["title"] == "结算记录"
        assert source["value"] == "11"
        assert source["link"] is None
        assert "snapshot" not in str(source)

    def test_issue_note_and_source_catalog_not_public(self):
        result = _result(
            fields=[_field(citation_refs=["rule.person_type_codes.issue78"])],
            citations=[
                CitationModel(
                    id="rule.person_type_codes.issue78", kind="issue_note",
                    ref="https://github.com/example/issues/78", approval_status="pending"),
                CitationModel(
                    id="source.snapshot_read_meta", kind="source_catalog",
                    ref="internal", values=["content_hash=abc"]),
            ],
        )
        view = _view(result)
        # 样本/Issue 说明与读取元数据不得冒充正式政策
        assert view["sources"] == []
        assert view["fields"][0]["source_refs"] == []

    def test_policy_document_link_only_https(self):
        result = _result(citations=[
            CitationModel(
                id="rule.a", kind="policy_document",
                ref="https://gov.example/policy/1", value="EOP-DED-001",
                approval_status="confirmed"),
            CitationModel(
                id="rule.b", kind="policy_document",
                ref="docs/internal/spec.csv", value="EOP-DED-002",
                approval_status="pending"),
            CitationModel(
                id="rule.c", kind="policy_document",
                ref="javascript:alert(1)", value="EOP-DED-003"),
        ])
        sources = {s["ref_id"]: s for s in _view(result)["sources"]}
        assert sources["rule.a"]["link"] == "https://gov.example/policy/1"
        assert sources["rule.a"]["confirmation_status"] == "confirmed"
        assert sources["rule.b"]["link"] is None
        # 待确认状态如实保留，不升级
        assert sources["rule.b"]["confirmation_status"] == "pending"
        assert sources["rule.c"]["link"] is None

    def test_unknown_kind_excluded(self):
        result = _result(citations=[CitationModel(
            id="x", kind="internal_audit", ref="r", value="v")])
        assert _view(result)["sources"] == []


class TestConditionProjection:
    def test_condition_projected_with_module_label(self):
        result = _result(branches=[BranchTraceModel(
            step_id="deductible.split", module_id="deductible", outcome="true",
            condition=BranchConditionModel(
                code="deductible_split", description="起付线按规则拆分",
                operator="formula", actual_value="100.00", expected_ref="EOP-DED-001"),
            calculation_refs=["calc.deductible.split"],
        )])
        condition = _view(result)["conditions"][0]
        assert condition["module_label"] == "起付线"
        assert condition["description"] == "起付线按规则拆分"
        assert condition["actual_display"] == "100.00"
        assert condition["expected_display"] == "EOP-DED-001"
        assert condition["outcome"] == "true"
        assert condition["calculation_refs"] == ["calc.deductible.split"]

    def test_unknown_module_falls_back(self):
        result = _result(branches=[BranchTraceModel(
            step_id="x.y", module_id="internal_impl_name", outcome="false",
            condition=BranchConditionModel(
                code="c", description="某条件", operator="eq"),
        )])
        condition = _view(result)["conditions"][0]
        assert condition["module_label"] == "其他计算步骤"
        assert "internal_impl_name" not in str(condition)

    def test_detail_modules_and_missing_condition_skipped(self):
        result = _result(branches=[
            BranchTraceModel(
                step_id="catalog.line.1", module_id="catalog_split", outcome="true",
                condition=BranchConditionModel(
                    code="c", description="逐行目录匹配", operator="eq")),
            BranchTraceModel(step_id="s", module_id="deductible", outcome="true"),
        ])
        assert _view(result)["conditions"] == []


class TestCalculationAndBrief:
    def test_operand_resolution_and_intermediate_marks(self):
        calc = _calc(operands=[
            CalculationOperandModel(ref="T_FirstPay", value="100.00"),
            CalculationOperandModel(ref="calc.catalog.total_fee", value="200.00"),
            CalculationOperandModel(ref="calc.unknown", value="3.00"),
            CalculationOperandModel(ref="rule.EOP-X-001", value="0.5"),
            CalculationOperandModel(ref="fact.item.L1.fee", value="10.00"),
        ])
        other = CalculationRecordModel(
            calculation_id="calc.catalog.total_fee", formula_id="identity_fee_all_v1",
            formula_version="v1", result="200.00")
        result = _result(
            fields=[_field(field_code="T_FirstPay", label="起付线"),
                    _field(calculation_refs=["calc.identity.self_pay_all"])],
            calculations=[calc, other],
        )
        view = _view(result)
        operands = view["calculations"][0]["operands"]
        # field_code → 结算展示名；calc.* 已记录 → 展示名+中间量；未记录 → 计算中间量
        assert {key: operands[0][key] for key in ("display_name", "value", "is_intermediate")} == {
            "display_name": "起付线", "value": "100.00", "is_intermediate": False}
        assert operands[0]["input_ref"].startswith("input-")
        assert operands[1]["calculation_ref"] == "calc.catalog.total_fee"
        assert operands[1]["display_name"] == "总费用账面恒等（医保内＋医保外）"
        assert operands[1]["is_intermediate"] is True
        assert operands[2]["display_name"] == "计算中间量"
        assert operands[2]["is_intermediate"] is True
        assert operands[3]["display_name"] == "规则参数（EOP-X-001）"
        assert operands[4]["display_name"] == "结算记录数据项"

    def test_layout_projected(self):
        result = _result(calculations=[_calc()])
        assert _view(result)["calculations"][0]["layout"] == "sum"

    def test_identity_brief_with_signed_operands(self):
        result = _result(
            fields=[_field(calculation_refs=["calc.identity.self_pay_all"])],
            calculations=[_calc()],
        )
        view = _view(result)
        assert view["fields"][0]["brief"] is None
        assert view["fields"][0]["calculated_amount"] == "68.85"
        assert not view["fields"][0]["explainable"]
        assert "＝92.30 元" in view["calculations"][0]["formula"]
        assert "－" in view["calculations"][0]["formula"]

    def test_single_calculation_brief(self):
        result = _result(
            fields=[_field(
                check_type="independent_recalculation",
                calculation_refs=["calc.identity.self_pay_all"])],
            calculations=[_calc()],
        )
        field = _view(result)["fields"][0]
        assert field["brief"] is None  # 关联记录结果不等于目标金额，不能拼接原因。
        assert not field["explainable"]

    def test_brief_not_applicable_and_observed_only(self):
        result = _result(fields=[
            _field(field_code="T_A", check_status="not_applicable",
                   calculated_amount=None, difference=None,
                   explanation_level="unexplained"),
            _field(field_code="T_B", check_status="not_verifiable",
                   calculated_amount=None, difference=None,
                   explanation_level="observed_only"),
        ])
        briefs = [f["brief"] for f in _view(result)["fields"]]
        assert briefs == [None, None]

    def test_subtract_rest_layout_brief(self):
        """subtract_rest 布局：首项减其余各项，减号由布局给出（操作数无符号存储）。"""
        calc = CalculationRecordModel(
            calculation_id="calc.big_pay.self_pay", formula_id="big_self_pay_v1",
            formula_version="v1",
            operands=[
                CalculationOperandModel(ref="calc.deductible.copay_base", value="500.00"),
                CalculationOperandModel(ref="calc.big_pay", value="60.00"),
            ],
            result="440.00")
        result = _result(
            fields=[_field(check_type="independent_recalculation",
                           calculation_refs=["calc.big_pay.self_pay"])],
            calculations=[calc])
        view = _view(result)
        assert view["calculations"][0]["layout"] == "subtract_rest"
        assert view["fields"][0]["brief"] is None  # 上游未返回，金额诊断与解释分开。
        brief = view["calculations"][0]["formula"]
        assert "－" in brief and "＋" not in brief
        assert "440.00" in brief

    def test_input_ref_business_labels(self):
        calc = _calc(operands=[
            CalculationOperandModel(ref="input.secondary.total_out_scope", value="10.00"),
            CalculationOperandModel(ref="input.secondary.unknown_dim", value="1.00"),
        ])
        result = _result(calculations=[calc])
        operands = _view(result)["calculations"][0]["operands"]
        assert operands[0]["display_name"] == "医保外费用"
        assert operands[0]["is_intermediate"] is True
        assert operands[1]["display_name"] == "本单输入数据项"
        assert operands[1]["is_intermediate"] is True

    def test_zero_and_negative_amounts_preserved(self):
        result = _result(fields=[_field(
            observed_amount="0.00", calculated_amount="-5.00", difference="-5.00",
            check_status="mismatched", explanation_level="observed_only")])
        field = _view(result)["fields"][0]
        assert field["observed_amount"] == "0.00"
        assert field["difference"] == "-5.00"
        assert field["check_status"] == "mismatched"


class TestSanitizeCoverage:
    def test_all_public_text_leaves_sanitized(self):
        seen: list[str] = []

        def spy(value) -> str:
            seen.append(str(value))
            return str(value)

        result = _result(
            fields=[_field(calculation_refs=["calc.identity.self_pay_all"],
                           citation_refs=["fact.a"])],
            branches=[BranchTraceModel(
                step_id="s", module_id="deductible", outcome="true",
                condition=BranchConditionModel(
                    code="c", description="条件描述", operator="eq",
                    actual_value="实际值", expected_ref="期望值"))],
            calculations=[_calc()],
            citations=[CitationModel(
                id="fact.a", kind="settlement_fact", ref="snapshot:s/a",
                value="事实值", values=["数组值"])],
            uncertainties=[UncertaintyModel(
                id="u1", code="C", message="缺口消息")],
        )
        view = to_public_contract_dict(
            result, summary_text="摘要", summary_source="template", sanitize=spy)
        for expected in (
            "摘要", "最终个人承担", "缺口消息", "条件描述", "实际值", "期望值",
            "事实值", "数组值", "结算记录",
        ):
            assert expected in seen, f"未消毒文本叶: {expected}"
        # link 为 None（snapshot 引用本就不下发），金额数值不走消毒
        assert view["fields"][0]["observed_amount"] == "68.85"

    def test_sanitize_replaces_internal_text(self):
        def hide(value) -> str:
            text = str(value)
            return "已隐藏" if "yb_" in text else text

        result = _result(citations=[CitationModel(
            id="fact.a", kind="settlement_fact", ref="snapshot:s/a",
            value="yb_mzjyxx 原始列名")])
        view = to_public_contract_dict(
            result, summary_text="", summary_source="template", sanitize=hide)
        assert view["sources"][0]["value"] == "已隐藏"
