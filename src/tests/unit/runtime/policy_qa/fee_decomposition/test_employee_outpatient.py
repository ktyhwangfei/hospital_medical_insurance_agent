"""职工普通门诊流程编排单元测试（设计 §6.1/§7 端到端组合）。"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.domain.insurance.fee_decomposition import (
    AnnualAccumulation,
    CatalogKind,
    DecompositionSnapshot,
    DrugCatalogEntry,
    FeeLineItem,
    InstitutionProfile,
    ObservedSettlementAmounts,
    PersonProfile,
    RoundingMode,
    TradeAnchor,
)
from src.runtime.policy_qa.fee_decomposition.employee_outpatient import (
    decompose_employee_outpatient,
)

D = date
MODE = RoundingMode.HALF_UP


def _drug_item(fee: str, key="L1", occ=D(2024, 5, 20), **kw) -> FeeLineItem:
    base = dict(
        line_key=key, item_code="D001", catalog_kind=CatalogKind.DRUG,
        fee=Decimal(fee), fee_occurrence_date=occ, item_type="0",
    )
    base.update(kw)
    return FeeLineItem(**base)


def _catalog() -> tuple[DrugCatalogEntry, ...]:
    return (DrugCatalogEntry(
        entry_id="E1", item_code="D001",
        effective_date=D(2024, 1, 1), expiry_date=D(2024, 12, 31), sflb="无自付"),)


def _snapshot(
    items=(_drug_item("3000.00"),),
    person_code="11",
    observed=ObservedSettlementAmounts(
        fee_all=Decimal("3000.00"), fee_in=Decimal("3000.00"), fee_out=Decimal("0.00"),
        first_pay=Decimal("1800.00"), big_pay=Decimal("840.00"),
        big_self_pay=Decimal("360.00"), bc_pay=Decimal("0.00"),
        jc_pay=Decimal("0.00"), official_pay=Decimal("0.00")),
    insurance="employee", category="outpatient",
    person: PersonProfile | None = None,
    trade: TradeAnchor | None = None,
    accumulation: AnnualAccumulation | None = None,
    has_other_fund_channels=False,
) -> DecompositionSnapshot:
    return DecompositionSnapshot(
        settlement_ref="settlement:test",
        insurance_type=insurance, medical_category=category,
        trade=trade or TradeAnchor(trade_no="T001", trade_date=D(2024, 6, 1), hospital_code="H001"),
        person=person or PersonProfile(
            person_type_code=person_code, birth_date=None,
            is_disabled_veteran=False, public_medical_eligible=False),
        institution=InstitutionProfile(hospital_code="H001", h_level="1"),
        accumulation=accumulation or AnnualAccumulation(
            prior_in_scope_fee=Decimal("0.00"), prior_in_scope_fee_is_pre_trade=True,
            prior_fund_payment=Decimal("0.00"), prior_fund_payment_is_pre_trade=True,
            in_scope_basis_aligned=True),
        items=tuple(items),
        observed=observed,
        rounding_mode=MODE,
        drug_catalog=_catalog(),
        has_other_fund_channels=has_other_fund_channels,
    )


def _field(result, code: str):
    for f in result.fields:
        if f.field_code == code:
            return f
    raise AssertionError(f"field {code} not found: {[f.field_code for f in result.fields]}")


def _branch(result, step_id: str):
    for b in result.branches:
        if b.step_id == step_id:
            return b
    raise AssertionError(f"branch {step_id} not found: {[b.step_id for b in result.branches]}")


def _retire_payment_snapshot():
    """250元账单：医保内221.50、自付二8.50、全自费20；退役支付只作账面输入。"""
    return replace(_snapshot(
        items=(_drug_item("145.00", key="1"), _drug_item("85.00", key="2", item_code="D002"),
               _drug_item("20.00", key="3", item_code="D003")),
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("250.00"), fee_in=Decimal("221.50"), fee_out=Decimal("28.50"),
            first_pay=Decimal("0.00"), big_pay=Decimal("155.05"), big_self_pay=Decimal("66.45"),
            self_pay_2=Decimal("8.50"), bc_pay=Decimal("0.00"), jc_pay=Decimal("0.00"),
            official_pay=Decimal("0.00"), retire_officer_pay=Decimal("44.30"),
            bigill_pay=Decimal("0.00"), civil_pay=Decimal("0.00"),
            fund_pay=Decimal("199.35"), self_pay_all=Decimal("50.65")),
        accumulation=AnnualAccumulation(
            prior_in_scope_fee=Decimal("19169.50"), prior_in_scope_fee_is_pre_trade=True,
            prior_fund_payment=Decimal("12158.69"), prior_fund_payment_is_pre_trade=True,
            in_scope_basis_aligned=True),
        has_other_fund_channels=None,
    ), drug_catalog=_catalog() + (
        DrugCatalogEntry("E2", "D002", D(2024, 1, 1), D(2024, 12, 31),
                         sflb="有自付", self_pay_ratio=Decimal("0.1")),
        DrugCatalogEntry("E3", "D003", D(2024, 1, 1), D(2024, 12, 31), sflb="全自付"),
    ))


def test_retire_payment_is_observed_only_but_other_book_compositions_include_it():
    from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence
    from src.runtime.policy_qa.fee_decomposition.public_view import build_public_view_dict

    snapshot = _retire_payment_snapshot()
    result = decompose_employee_outpatient(snapshot)
    assert _field(result, "T_BigPay").calculated_amount == "155.05"
    own = _field(result, "RETIRE_OFFICER_PAY")
    assert own.observed_amount == "44.30"
    assert own.calculated_amount is None
    assert own.calculation_refs == []
    assert _field(result, "T_FundPay").check_status == "not_verifiable"  # 未声明渠道穷尽
    for code, value in (("T_FundPay.listed_channels", "199.35"), ("T_SelfPayAll", "50.65")):
        composed = _field(result, code)
        assert composed.check_type == "identity_check"
        assert composed.check_status == "matched"
        assert Decimal(composed.calculated_amount) == Decimal(value)
    view = build_public_view_dict(attach_evidence(result, snapshot), summary_text="", summary_source="template")
    fields = {field["field_code"]: field for field in view["fields"]}
    assert fields["RETIRE_OFFICER_PAY"]["explainable"] is False
    assert fields["T_SelfPayAll"]["explainable"] is False
    assert any("退役医疗费支付" in (calc["formula"] or "") for calc in view["calculations"])


def test_missing_retire_payment_cannot_reconcile_other_book_amounts():
    snapshot = _retire_payment_snapshot()
    result = decompose_employee_outpatient(replace(snapshot,
        observed=replace(snapshot.observed, retire_officer_pay=None)))
    for code in ("RETIRE_OFFICER_PAY", "T_FundPay.listed_channels", "T_SelfPayAll"):
        field = _field(result, code)
        assert field.check_status == "not_verifiable"
        assert field.calculated_amount is None
        assert field.calculation_refs == []


def test_happy_path_employed_complete():
    # 在职/其他医院/2024：E=3000，F=1800，B=1200，大额 70% = 840，S=360
    res = decompose_employee_outpatient(_snapshot())
    assert res.execution_status == "complete"
    assert res.algorithm_version == "employee_outpatient_v1"
    assert _field(res, "T_FeeAll").check_status == "matched"
    assert _field(res, "T_FirstPay").calculated_amount == "1800.00"
    assert _field(res, "T_FirstPay").check_status == "matched"
    assert _field(res, "T_BigPay").calculated_amount == "840.00"
    assert _field(res, "T_BigSelfPay").calculated_amount == "360.00"
    # 在职无退休/军残/公疗：not_applicable 且账面为零不冲突
    assert _field(res, "T_BCPay").check_status == "not_applicable"
    assert _branch(res, "person.classify").outcome == "true"
    assert _branch(res, "rsup.eligibility").outcome == "not_applicable"
    # 账户/现金无当时扣款规则 → 不可核对；整体核对轴 not_verifiable，不宣称完整解释
    assert _field(res, "T_CashPay").check_status == "not_verifiable"
    assert res.reconciliation_status == "not_verifiable"
    assert res.answer_constraints.may_claim_full_explanation is False
    assert res.answer_constraints.may_infer_missing_rules is False
    # 取整规则待确认的全局不确定性始终存在
    assert any(u.code == "ROUNDING_RULE_PENDING_CONFIRMATION" for u in res.uncertainties)


def test_unsupported_profile_not_reusing_employee_formula():
    res = decompose_employee_outpatient(_snapshot(insurance="resident"))
    assert res.execution_status == "unavailable"
    assert res.fields == []
    assert _branch(res, "flow.profile_select").outcome == "not_applicable"
    assert any(u.code == "UNSUPPORTED_PROFILE" for u in res.uncertainties)


def test_reversal_or_negative_items_unavailable():
    res = decompose_employee_outpatient(_snapshot(items=(_drug_item("-50.00"),)))
    assert res.execution_status == "unavailable"
    assert any(u.code == "UNSUPPORTED_REVERSAL_OR_NEGATIVE" for u in res.uncertainties)
    res2 = decompose_employee_outpatient(_snapshot(
        trade=TradeAnchor(trade_no="T002", trade_date=D(2024, 6, 1), hospital_code="H001",
                          is_reversal=True)))
    assert res2.execution_status == "unavailable"


def test_duplicate_line_keys_unavailable():
    res = decompose_employee_outpatient(_snapshot(items=(_drug_item("100.00"), _drug_item("200.00"))))
    assert res.execution_status == "unavailable"
    assert any(u.code == "DUPLICATE_LINE_KEY" for u in res.uncertainties)


def test_lower_bound_accumulation_not_reported_as_explained():
    """累计只是同院历史下界时，只放行与其无关的字段，封顶/分段结论不得算平。"""
    res = decompose_employee_outpatient(_snapshot(accumulation=AnnualAccumulation(
        prior_in_scope_fee=Decimal("4400.00"), prior_in_scope_fee_is_pre_trade=False,
        prior_fund_payment=Decimal("4400.00"), prior_fund_payment_is_pre_trade=False,
        in_scope_basis_aligned=False, prior_is_lower_bound=True)))
    assert _field(res, "T_FeeIn").check_status == "matched"
    for code in ("T_FirstPay", "T_BigPay", "T_SelfPayAll"):
        assert _field(res, code).check_status != "matched", code


def test_unknown_person_code_partial_not_defaulted():
    res = decompose_employee_outpatient(_snapshot(person_code="77X"))
    assert res.execution_status == "partial"
    assert _branch(res, "person.classify").outcome == "unknown"
    assert _field(res, "T_FirstPay").check_status == "not_verifiable"
    # 禁止反推：起付计算值不取自账面 T_FirstPay
    assert _field(res, "T_FirstPay").calculated_amount is None


def test_retired_veteran_chain():
    # 退休<70 其他医院：E=1500，F=1300，B=200，大额 70%=140，S=60；R=30（50%），J=15（(60-30)×50%）
    person = PersonProfile(
        person_type_code="21", birth_date=D(1960, 1, 1),
        retirement_category="normal", retire_supplement_enroll_date=D(2006, 4, 1),
        is_disabled_veteran=True, military_disability_grade="5-6",
        military_eligible_from=D(2000, 1, 1),
        is_rural_disabled_veteran=False, public_medical_eligible=False)
    res = decompose_employee_outpatient(_snapshot(
        items=(_drug_item("1500.00"),), person=person,
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("1500.00"), fee_in=Decimal("1500.00"),
            first_pay=Decimal("1300.00"), big_pay=Decimal("140.00"),
            big_self_pay=Decimal("60.00"), bc_pay=Decimal("30.00"), jc_pay=Decimal("15.00"))))
    assert _field(res, "T_BCPay").calculated_amount == "30.00"
    assert _field(res, "T_BCPay").check_status == "matched"
    assert _field(res, "T_JCPay").calculated_amount == "15.00"


def test_rural_veteran_public_medical_skips_military():
    # 在乡残疾军人享受公疗：跳过军残；G=200（1500-1300），prior=大额140+退休30=170，O=200×100%-170=30
    person = PersonProfile(
        person_type_code="21", birth_date=D(1960, 1, 1),
        retirement_category="normal", retire_supplement_enroll_date=D(2006, 4, 1),
        is_disabled_veteran=True, military_disability_grade="5-6",
        military_eligible_from=D(2000, 1, 1),
        is_rural_disabled_veteran=True,
        public_medical_eligible=True, public_medical_designated=True)
    res = decompose_employee_outpatient(_snapshot(
        items=(_drug_item("1500.00"),), person=person,
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("1500.00"), fee_in=Decimal("1500.00"),
            first_pay=Decimal("1300.00"), big_pay=Decimal("140.00"),
            big_self_pay=Decimal("60.00"), bc_pay=Decimal("30.00"),
            jc_pay=Decimal("0.00"), official_pay=Decimal("30.00"))))
    assert _field(res, "T_JCPay").check_status == "not_applicable"
    assert _branch(res, "dvet.rural_pmed_exclusion").reason_code == (
        "RURAL_DISABLED_VETERAN_PUBLIC_MEDICAL_EXCLUSION")
    assert _field(res, "T_OfficalPay").calculated_amount == "30.00"
    assert _field(res, "T_OfficalPay").check_status == "matched"


def test_fund_channels_not_exhausted_disables_identity():
    res = decompose_employee_outpatient(_snapshot(has_other_fund_channels=True))
    f = _field(res, "T_FundPay")
    assert f.check_status == "not_applicable"
    assert f.reason_code == "FUND_CHANNELS_NOT_EXHAUSTED"
    assert f.check_type == "identity_check"


def test_mismatched_observed_keeps_difference():
    # 账面大额支付与独立重算差一分钱 → mismatched，差异保留
    res = decompose_employee_outpatient(_snapshot(
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("3000.00"), fee_in=Decimal("3000.00"),
            first_pay=Decimal("1800.00"), big_pay=Decimal("839.99"))))
    f = _field(res, "T_BigPay")
    assert f.check_status == "mismatched"
    assert f.difference == "0.01"
    assert res.reconciliation_status == "mismatched"


def test_self_pay_all_channel_identity_recorded():
    # 渠道恒等（解释投影 1.1，对照居民链）：账户+现金 = 最终个人承担，
    # 分量齐全时落 calc.identity.self_pay_all_channel 轨迹记录
    res = decompose_employee_outpatient(_snapshot(
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("3000.00"), fee_in=Decimal("3000.00"), fee_out=Decimal("0.00"),
            first_pay=Decimal("1800.00"), big_pay=Decimal("840.00"),
            big_self_pay=Decimal("360.00"), bc_pay=Decimal("0.00"),
            jc_pay=Decimal("0.00"), official_pay=Decimal("0.00"),
            self_pay_all=Decimal("2160.00"),
            person_count_pay=Decimal("1000.00"), cash_pay=Decimal("1160.00"))))
    f = _field(res, "T_SelfPayAll.channel")
    assert f.check_type == "identity_check"
    assert f.check_status == "matched"
    assert "calc.identity.self_pay_all_channel" in f.calculation_refs
    calc = next(c for c in res.calculations
                if c.calculation_id == "calc.identity.self_pay_all_channel")
    assert calc.formula_id == "identity_self_pay_channel_v1"
    assert calc.result == "2160.00"


def test_self_pay_all_channel_identity_components_missing_no_calc():
    # 渠道分量不齐：沿用 _identity_entry 降级——字段 not_verifiable 且不产生产记录
    res = decompose_employee_outpatient(_snapshot())
    f = _field(res, "T_SelfPayAll.channel")
    assert f.check_status == "not_verifiable"
    assert f.calculation_refs == []
    assert not any(c.calculation_id == "calc.identity.self_pay_all_channel"
                   for c in res.calculations)


def test_rounding_mode_is_explicit_required():
    # EOP-RND-001 待确认：取整模式必须显式传入，无默认
    with pytest.raises(TypeError):
        DecompositionSnapshot(  # type: ignore[call-arg]
            settlement_ref="s", insurance_type="employee", medical_category="outpatient",
            trade=TradeAnchor(trade_no="T", trade_date=D(2024, 1, 1), hospital_code="H"),
            person=PersonProfile(person_type_code="11", birth_date=None),
            institution=InstitutionProfile(hospital_code="H", h_level="1"),
            accumulation=AnnualAccumulation(prior_in_scope_fee=Decimal("0")),
            items=(), observed=ObservedSettlementAmounts(),
        )


def test_officially_verified_rule_input_is_verified():
    """确认口径统一：官方已核实 与 文档明确 同属已确认集合，选中规则输入判 verified。"""
    from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence

    snap = _snapshot()
    res = attach_evidence(decompose_employee_outpatient(snap), snap)
    node = res.explanation_evidence.inputs["rule.EOP-RATE-106"]  # 官方已核实，本单选中
    assert node.status == "verified"
    assert node.reason is None


def test_pending_confirmation_status_stays_unverified():
    """含"待"字的状态不放行：文档明确-待官方核证 的选中规则输入仍为 unverified 且携带原状态。"""
    from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence

    snap = _snapshot()
    res = attach_evidence(decompose_employee_outpatient(snap), snap)
    node = res.explanation_evidence.inputs["rule.EOP-DED-002"]  # 文档明确-待官方核证，本单选中
    assert node.status == "unverified"
    assert node.reason is not None and "文档明确-待官方核证" in node.reason
