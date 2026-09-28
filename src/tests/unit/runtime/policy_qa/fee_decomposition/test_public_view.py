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


class TestBuildPublicViewDict:
    def test_mapping_and_amount_passthrough(self):
        result = _result(fields=[_field()], uncertainties=[UncertaintyModel(
            id="u1", code="C1", message="m1")])
        view = build_public_view_dict(result, summary_text="s", summary_source="template")
        assert view["schema_version"] == "1.0"
        assert view["algorithm_version"] == "employee_outpatient_v1"
        assert view["execution_status"] == "complete"
        assert view["reconciliation_status"] == "matched"
        assert view["may_claim_full_explanation"] is True
        assert view["summary_text"] == "s"
        assert view["summary_source"] == "template"
        assert view["fields"][0]["observed_amount"] == "60.00"
        assert view["fields"][0]["calculated_amount"] == "60.00"
        assert view["uncertainties"] == [{"code": "C1", "message": "m1"}]
        assert view["coverage"]["target_field_count"] == 1

    def test_audit_details_excluded(self):
        result = _result(fields=[_field()])
        result.branches.append(BranchTraceModel(step_id="s", module_id="m", outcome="true"))
        view = build_public_view_dict(result, summary_text="", summary_source="template")
        assert "branches" not in view
        assert "calculations" not in view
        assert "citations" not in view
        assert "settlement_ref" not in view
        assert "profile" not in view
