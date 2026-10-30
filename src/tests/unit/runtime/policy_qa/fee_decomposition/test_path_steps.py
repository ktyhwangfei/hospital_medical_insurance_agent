"""正向结算路径投影（path_steps）与公开契约 1.2 单元测试（Issue #78 费用解释改造）。

覆盖：
- 职工门诊链：步骤白名单序（费用明细→目录划分→起付→大额→补助→个人支付→支付方式），
  金额来自本单结算 calc.result，多金额步 amount=None 由 field_refs 展开（不补算）；
- 状态判定：applied / zero_amount（零金额≠不适用）/ not_applicable（分支 outcome）
  / unknown（保留）/ observed_only（无结算 calc 但字段有账面值）；
- 缺 calc 引用降级：calculation_refs 只保留能在 calculations 索引解析的；
- 门特链：calc.detail.* / xjzf_channel 系；未执行模块不出现该步；
- 契约 1.2：旧 1.1 载荷（无两新块）仍可校验；extra=forbid 拒脏键；文本叶消毒。
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.runtime.policy_qa.fee_decomposition.public_view import (
    PUBLIC_SCHEMA_VERSION,
    build_public_view_dict,
    to_public_contract_dict,
)
from src.runtime.policy_qa.fee_decomposition.result import (
    AnswerConstraints,
    BranchConditionModel,
    BranchTraceModel,
    CalculationRecordModel,
    CoverageSummary,
    DecompositionProfile,
    FieldExplanationModel,
    SettlementDecompositionResult,
)
from src.runtime.policy_qa.fee_decomposition.settlement_facts import (
    SettlementFactsItem,
    SettlementFactsView,
)
from src.runtime.policy_qa.public_contract import FeeDecompositionPublic


def _calc(calc_id: str, result: str | None) -> CalculationRecordModel:
    return CalculationRecordModel(
        calculation_id=calc_id, formula_id="f", formula_version="v1", result=result)


def _branch(step_id: str, module_id: str, outcome: str,
            calc_refs: tuple[str, ...] = (), condition: bool = False) -> BranchTraceModel:
    return BranchTraceModel(
        step_id=step_id, module_id=module_id, outcome=outcome,
        condition=BranchConditionModel(
            code="c", description=f"{step_id} 条件", operator="eq",
            actual_value="1", expected_ref="规则") if condition else None,
        calculation_refs=list(calc_refs))


def _field(field_code: str, observed: str | None = None) -> FieldExplanationModel:
    return FieldExplanationModel(
        field_code=field_code, label=field_code, check_type="independent_recalculation",
        check_status="matched", observed_amount=observed,
        calculated_amount=observed, difference="0.00",
        explanation_level="amount_reconciled")


def _result(*, branches=(), calcs=(), fields=()) -> SettlementDecompositionResult:
    fields = list(fields)
    return SettlementDecompositionResult(
        settlement_ref="settlement:T001",
        profile=DecompositionProfile(insurance_type="employee", medical_category="outpatient"),
        execution_status="complete", reconciliation_status="matched",
        fields=fields, branches=list(branches), calculations=list(calcs),
        coverage=CoverageSummary(
            target_field_count=len(fields), independently_explained_count=0,
            amount_reconciled_count=0, observed_only_count=0),
        answer_constraints=AnswerConstraints(may_claim_full_explanation=True),
    )


def _steps(view: dict) -> dict[str, dict]:
    return {s["step_id"]: s for s in view["path_steps"]}


def _employee_like(**overrides) -> SettlementDecompositionResult:
    """职工门诊正向链：目录→起付→大额→补助（不适用）→个人支付→支付方式。"""
    branches = overrides.pop("branches", None)
    if branches is None:
        branches = [
            _branch("catalog.summary", "catalog_split", "true"),
            _branch("deductible.split", "deductible", "true",
                    ("calc.deductible.split",), condition=True),
            _branch("big_pay.settle", "big_pay", "true",
                    ("calc.big_pay.capped",), condition=True),
            _branch("rsup.eligibility", "retire_supplement", "not_applicable", condition=True),
            _branch("dvet.eligibility", "military_supplement", "not_applicable"),
            _branch("pmed.eligibility", "public_medical", "not_applicable"),
        ]
    calcs = overrides.pop("calcs", None)
    if calcs is None:
        calcs = [
            _calc("calc.catalog.total_fee", "3000.00"),
            _calc("calc.catalog.total_in_scope", "3000.00"),
            _calc("calc.catalog.total_out_scope", "0.00"),
            _calc("calc.deductible.split", "1800.00"),
            _calc("calc.big_pay.capped", "1080.00"),
            _calc("calc.identity.self_pay_all", "1920.00"),
            _calc("calc.identity.self_pay_all_channel", "1920.00"),
        ]
    fields = overrides.pop("fields", None)
    if fields is None:
        fields = [
            _field("T_FeeAll", "3000.00"), _field("T_FeeIn", "3000.00"),
            _field("T_FeeOut", "0.00"), _field("T_SelfPay2", "0.00"),
            _field("T_FirstPay", "1800.00"), _field("T_BigPay", "1080.00"),
            _field("T_BigSelfPay", "120.00"), _field("T_SelfPayAll", "1920.00"),
            _field("T_PersonCountPay", "0.00"), _field("T_CashPay", "1920.00"),
        ]
    return _result(branches=branches, calcs=calcs, fields=fields)


class TestEmployeePathSteps:
    def test_step_order_and_amounts(self):
        view = build_public_view_dict(
            _employee_like(), summary_text="", summary_source="template")
        assert [s["step_id"] for s in view["path_steps"]] == [
            "path.fee_items", "path.catalog_split", "path.deductible", "path.fund",
            "path.supplements", "path.personal_total", "path.payment_method",
        ]
        steps = _steps(view)
        assert steps["path.fee_items"]["name"] == "费用明细"
        assert steps["path.fee_items"]["status"] == "applied"
        assert steps["path.fee_items"]["amount"] == "3000.00"
        # 目录划分：医保内/外两个金额 → amount=None，前端按 field_refs 展开（不补算）
        assert steps["path.catalog_split"]["amount"] is None
        assert steps["path.catalog_split"]["field_refs"] == ["T_FeeIn", "T_FeeOut", "T_SelfPay2"]
        assert steps["path.deductible"]["status"] == "applied"
        assert steps["path.deductible"]["amount"] == "1800.00"
        assert "deductible.split 条件" in steps["path.deductible"]["reason"]
        assert steps["path.fund"]["amount"] == "1080.00"
        # 补助全不适用：分支 outcome=not_applicable（零金额≠不适用）
        assert steps["path.supplements"]["status"] == "not_applicable"
        assert steps["path.supplements"]["amount"] is None
        # 个人支付/支付方式两步恒出现（字段存在）
        assert steps["path.personal_total"]["amount"] == "1920.00"
        assert steps["path.personal_total"]["field_refs"] == ["T_SelfPayAll"]
        assert steps["path.payment_method"]["amount"] == "1920.00"
        assert steps["path.payment_method"]["field_refs"] == [
            "T_PersonCountPay", "T_CashPay"]
        # 未执行模块（大病/救助）不出现该步
        assert "path.secondary" not in steps

    def test_zero_amount_is_not_not_applicable(self):
        result = _employee_like(
            calcs=[_calc("calc.catalog.total_fee", "100.00"),
                   _calc("calc.big_pay.capped", "0.00")])
        steps = _steps(build_public_view_dict(
            result, summary_text="", summary_source="template"))
        assert steps["path.fund"]["status"] == "zero_amount"
        assert steps["path.fund"]["amount"] == "0.00"

    def test_unknown_preserved(self):
        result = _employee_like(
            branches=[_branch("deductible.base_available", "deductible", "unknown",
                              condition=True)],
            calcs=[], fields=[_field("T_FirstPay", "1800.00")])
        steps = _steps(build_public_view_dict(
            result, summary_text="", summary_source="template"))
        # unknown 保留：不因字段有账面值而升级为 observed_only
        assert steps["path.deductible"]["status"] == "unknown"
        assert steps["path.deductible"]["amount"] is None

    def test_observed_only_when_no_settle_calc(self):
        result = _employee_like(
            branches=[_branch("deductible.split", "deductible", "true", condition=True)],
            calcs=[], fields=[_field("T_FirstPay", "1800.00")])
        steps = _steps(build_public_view_dict(
            result, summary_text="", summary_source="template"))
        assert steps["path.deductible"]["status"] == "observed_only"
        assert steps["path.deductible"]["amount"] == "1800.00"  # 账面观测值

    def test_calc_refs_degrade_to_resolvable(self):
        result = _employee_like(
            branches=[_branch("big_pay.settle", "big_pay", "true",
                              ("calc.big_pay.capped", "calc.big_pay.ghost"))],
            calcs=[_calc("calc.big_pay.capped", "1080.00")])
        steps = _steps(build_public_view_dict(
            result, summary_text="", summary_source="template"))
        assert steps["path.fund"]["calculation_refs"] == ["calc.big_pay.capped"]


class TestSpecialPathSteps:
    def test_special_chain_projection(self):
        """门特链：calc.detail.* 汇总、居民门特起付模块、xjzf_channel 恒等。"""
        result = _result(
            branches=[
                _branch("detail.aggregation", "detail_aggregation", "true",
                        ("calc.detail.total_in_scope",)),
                _branch("deductible.split", "resident_special_deductible", "true",
                        ("calc.deductible.split",)),
            ],
            calcs=[
                _calc("calc.detail.total_in_scope", "90.00"),
                _calc("calc.deductible.split", "0.00"),
                _calc("calc.identity.xjzf_channel", "20.00"),
            ],
            fields=[
                _field("ZJE", "100.00"), _field("TSBYBN", "90.00"),
                _field("YBNQFJE", "0.00"),
                _field("XJZF", "20.00"), _field("ZHZF", "0.00"),
            ],
        )
        steps = _steps(build_public_view_dict(
            result, summary_text="", summary_source="template"))
        assert steps["path.fee_items"]["amount"] == "100.00"
        assert steps["path.fee_items"]["status"] == "observed_only"
        assert steps["path.catalog_split"]["name"] == "明细已有划分汇总"
        # 零金额起付：zero_amount，不宣称不适用
        assert steps["path.deductible"]["status"] == "zero_amount"
        assert steps["path.deductible"]["amount"] == "0.00"
        # 门特无 T_SelfPayAll 字段 → 个人支付步不出现
        assert "path.personal_total" not in steps
        # 支付方式：xjzf_channel 恒等 + XJZF/ZHZF 字段
        assert steps["path.payment_method"]["amount"] == "20.00"
        assert steps["path.payment_method"]["field_refs"] == ["XJZF", "ZHZF"]


def test_terminal_calculations_are_linked_without_branch_refs():
    steps = _steps(build_public_view_dict(
        _employee_like(), summary_text="", summary_source="template"))
    assert steps["path.fee_items"]["calculation_refs"] == ["calc.catalog.total_fee"]
    assert steps["path.personal_total"]["calculation_refs"] == ["calc.identity.self_pay_all"]
    assert steps["path.payment_method"]["calculation_refs"] == ["calc.identity.self_pay_all_channel"]


def test_partial_group_is_unknown_and_keeps_known_calculation():
    result = _result(
        branches=[_branch("pool.settle", "pool_fund", "true", ("calc.pool.segmented",)),
                  _branch("large.guard", "large_fund", "unknown")],
        calcs=[_calc("calc.pool.segmented", "20.00")])
    step = _steps(build_public_view_dict(result, summary_text="", summary_source="template"))["path.fund"]
    assert step["status"] == "unknown"
    assert step["amount"] is None
    assert step["calculation_refs"] == ["calc.pool.segmented"]


def test_secondary_coverage_ends_in_personal_total():
    result = _result(
        branches=[_branch("secondary.pay", "secondary_coverage", "true")],
        calcs=[_calc("calc.secondary.big_ill_pay", "0.00"),
               _calc("calc.secondary.civil_in", "0.00"),
               _calc("calc.secondary.person_payable", "25.00")],
        fields=[_field("BIG_ILL_PAY", "0.00"), _field("CIVIL_IN", "0.00"),
                _field("PERSON_PAYABLE", "25.00")])
    steps = _steps(build_public_view_dict(result, summary_text="", summary_source="template"))
    assert steps["path.secondary"]["status"] == "zero_amount"
    assert steps["path.personal_total"]["amount"] == "25.00"


def test_resident_medical_service_payment_is_in_path():
    result = _result(
        branches=[_branch("msf.full", "resident_msf_pay", "true", ("calc.msf_pay.full",))],
        calcs=[_calc("calc.msf_pay.full", "40.00")], fields=[_field("T_BigPay", "40.00")])
    steps = _steps(build_public_view_dict(result, summary_text="", summary_source="template"))
    assert steps["path.fund"]["amount"] == "40.00"


def test_fixed_hospital_fund_is_kept_separate_from_patient_fund():
    result = _result(
        branches=[_branch("fixed.hospital_fund", "fixed_quota", "true", ("calc.fixed.hospital_fund",)),
                  _branch("pool.settle", "pool_fund", "true", ("calc.pool.segmented",), condition=True)],
        calcs=[_calc("calc.fixed.hospital_fund", "5000.00"), _calc("calc.pool.segmented", "100.00")],
        fields=[_field("TCZHF", "5000.00")])
    steps = _steps(build_public_view_dict(result, summary_text="", summary_source="template"))
    assert steps["path.fund"]["name"] == "医院定额基金（条件口径）"
    assert steps["path.fund"]["amount"] == "5000.00"
    assert steps["path.fund"]["calculation_refs"] == ["calc.fixed.hospital_fund"]
    assert steps["path.fund"]["reason"] is None


def test_full_self_pay_keeps_detail_step_and_real_branch_reason():
    from src.runtime.policy_qa.fee_decomposition.employee_outpatient import decompose_employee_outpatient
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_batch_decisions import _snapshot_no_benefit
    result = decompose_employee_outpatient(_snapshot_no_benefit())
    steps = _steps(build_public_view_dict(result, summary_text="", summary_source="template"))
    assert steps["path.fee_items"]["amount"] == "250.00"
    assert "无待遇原因码" in steps["path.personal_total"]["reason"]
    assert "path.catalog_split" not in steps  # 未执行目录重算，不补造步骤


def test_fixed_fund_record_does_not_add_quota_self_pay_and_coordinates():
    from src.runtime.policy_qa.fee_decomposition.formula_display import formula_display
    assert formula_display("fixed_quota_minus_original_self_pay").layout == "generic"


# ── 公开契约 1.2 ──────────────────────────────────────────────────


def _facts() -> SettlementFactsView:
    return SettlementFactsView(
        chain="outpatient", identifier="T001", trade_date="2024-06-01",
        medical_category="11", insurance_type="3", person_type="11",
        hospital_level=None,
        items=[SettlementFactsItem(label="费用总金额", value="100.00")],
        payment_items=[SettlementFactsItem(label="个人账户支付", value="0.00")],
    )


class TestPublicContract13:
    def test_version_bumped_to_17(self):
        assert PUBLIC_SCHEMA_VERSION == "1.10"
        view = build_public_view_dict(
            _result(), summary_text="", summary_source="template")
        assert view["schema_version"] == "1.10"
        assert view["path_steps"] == []
        assert view["settlement_facts"] is None

    def test_settlement_facts_carried_into_view(self):
        view = build_public_view_dict(
            _result(), summary_text="", summary_source="template",
            settlement_facts=_facts())
        facts = view["settlement_facts"]
        assert facts["chain"] == "outpatient"
        assert facts["items"] == [{"label": "费用总金额", "value": "100.00"}]
        assert facts["payment_items"] == [{"label": "个人账户支付", "value": "0.00"}]

    def test_legacy_11_payload_still_validates(self):
        """旧 1.1 载荷（无 settlement_facts/path_steps 两新块）仍可被契约校验。"""
        view = build_public_view_dict(
            _employee_like(), summary_text="s", summary_source="template")
        legacy = {k: v for k, v in view.items()
                  if k not in ("settlement_facts", "path_steps")}
        legacy["schema_version"] = "1.1"
        public = FeeDecompositionPublic.model_validate(legacy)
        assert public.settlement_facts is None
        assert public.path_steps == []
        dumped = public.model_dump()
        # 空值不落键（与 calculations/sources/conditions 的 exclude_if 惯例一致）
        assert "settlement_facts" not in dumped
        assert "path_steps" not in dumped

    def test_full_payload_validates_and_round_trips(self):
        view = build_public_view_dict(
            _employee_like(), summary_text="s", summary_source="template",
            settlement_facts=_facts())
        public = FeeDecompositionPublic.model_validate(view)
        dumped = public.model_dump()
        assert dumped["settlement_facts"]["identifier"] == "T001"
        assert dumped["path_steps"][0]["step_id"] == "path.fee_items"

    def test_extra_forbid_rejects_dirty_keys(self):
        view = build_public_view_dict(
            _result(), summary_text="", summary_source="template")
        with pytest.raises(ValidationError):
            FeeDecompositionPublic.model_validate({**view, "internal_note": "x"})
        step = view["path_steps"]
        assert step == []

    def test_path_step_extra_forbid(self):
        view = build_public_view_dict(
            _employee_like(), summary_text="", summary_source="template",
            settlement_facts=_facts())
        dirty = dict(view)
        dirty["path_steps"] = [dict(view["path_steps"][0], sql="SELECT 1")]
        with pytest.raises(ValidationError):
            FeeDecompositionPublic.model_validate(dirty)


class TestSanitizationCoversNewBlocks:
    def test_facts_and_path_text_leaves_sanitized(self):
        facts = SettlementFactsView(
            chain="outpatient", identifier="T001", trade_date=None,
            medical_category=None, insurance_type=None, person_type=None,
            hospital_level=None,
            items=[SettlementFactsItem(label="参照 yb_mzjyxx 表", value="100.00")],
            payment_items=[],
        )
        result = _result(
            branches=[_branch("deductible.split", "deductible", "true",
                              ("calc.deductible.split",), condition=True)],
            calcs=[_calc("calc.deductible.split", "1.00")],
        )
        result.branches[0].condition.description = "起付条件见 yb_mzjyxx"
        view = to_public_contract_dict(
            result, summary_text="", summary_source="template",
            settlement_facts=facts,
            sanitize=lambda v: v.replace("yb_mzjyxx", "结算数据字段"))
        assert view["settlement_facts"]["items"][0]["label"] == "参照 结算数据字段 表"
        step = {s["step_id"]: s for s in view["path_steps"]}["path.deductible"]
        assert "yb_mzjyxx" not in (step["reason"] or "")
