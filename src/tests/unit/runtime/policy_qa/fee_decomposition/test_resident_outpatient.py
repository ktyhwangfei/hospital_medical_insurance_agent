"""城乡居民普通门诊费用分解内核单元测试（Issue #80）。

覆盖：门诊大额通道（19/11）、医事服务费通道（17/18）、退费交易（区间重叠公式）、
无待遇全额自费（含负值镜像）、封顶 clamp、机构等级档、补充待遇不适用、profile 守卫。

测试快照形态取自 bjybdb 真实交易（见 scripts/eval/issue80_data_probe.py 探查记录）。
"""
from __future__ import annotations

from datetime import date
from dataclasses import replace
from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    AnnualAccumulation,
    CatalogKind,
    DecompositionSnapshot,
    DrugCatalogEntry,
    FeeLineItem,
    InstitutionProfile,
    MaterialCatalogEntry,
    ObservedSettlementAmounts,
    PersonProfile,
    RoundingMode,
    ServiceCatalogEntry,
    TradeAnchor,
    OriginalPolicyContext,
)
from src.runtime.policy_qa.fee_decomposition.resident_outpatient import (
    ALGORITHM_VERSION,
    decompose_resident_outpatient,
)

D = date
MODE = RoundingMode.HALF_UP


def _drug_item(fee: str, key="L1", occ=D(2024, 9, 13), **kw) -> FeeLineItem:
    base = dict(
        line_key=key, item_code="D001", catalog_kind=CatalogKind.DRUG,
        fee=Decimal(fee), fee_occurrence_date=occ, item_type="0",
    )
    base.update(kw)
    return FeeLineItem(**base)


def _drug_catalog() -> tuple[DrugCatalogEntry, ...]:
    return (DrugCatalogEntry(
        entry_id="E1", item_code="D001",
        effective_date=D(2024, 1, 1), expiry_date=D(2024, 12, 31), sflb="0101",
        self_pay_ratio=Decimal("0")),)


def _snapshot(
    items=None,
    observed: ObservedSettlementAmounts | None = None,
    insurance="resident", category="outpatient",
    cure_type="19",
    no_right_reason=None,
    original_trade_no=None,
    h_level="02",
    person_code="15",
    prior_in_scope="0.00",
    prior_fund="0.00",
    accumulation_confirmed=True,
) -> DecompositionSnapshot:
    if items is None:
        items = (_drug_item("168.00"),)
    snapshot = DecompositionSnapshot(
        settlement_ref="settlement:test",
        insurance_type=insurance, medical_category=category,
        trade=TradeAnchor(
            trade_no="T001", trade_date=D(2024, 9, 13), hospital_code="01110003",
            original_trade_no=original_trade_no, no_right_reason=no_right_reason,
            cure_type=cure_type, fund_type="91"),
        person=PersonProfile(person_type_code=person_code, birth_date=D(2011, 1, 1)),
        institution=InstitutionProfile(hospital_code="01110003", h_level=h_level, h_type="01"),
        accumulation=AnnualAccumulation(
            prior_in_scope_fee=Decimal(prior_in_scope),
            prior_in_scope_fee_is_pre_trade=accumulation_confirmed,
            prior_fund_payment=Decimal(prior_fund),
            prior_fund_payment_is_pre_trade=accumulation_confirmed),
        items=tuple(items),
        observed=observed or ObservedSettlementAmounts(),
        rounding_mode=MODE,
        drug_catalog=_drug_catalog(),
    )
    # 镜像用例显式提供同日原单事实；缺失原单的回归单独清空此上下文。
    if original_trade_no:
        snapshot = replace(snapshot, original_policy_context=OriginalPolicyContext(
            D(2024, 9, 13), snapshot.person, snapshot.institution,
            insurance, category, 2024, cure_type, no_right_reason))
    return snapshot


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


def test_happy_path_deductible_partial():
    """样本 011100030X240913000154 形态：A=527、E=168 → F=550−527=23、B=145、BigPay=72.5。"""
    res = decompose_resident_outpatient(_snapshot(
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("168"), fee_in=Decimal("168"), fee_out=Decimal("0"),
            self_pay_2=Decimal("0"), first_pay=Decimal("23"), big_pay=Decimal("72.50"),
            big_self_pay=Decimal("72.50"), bc_pay=Decimal("0"), jc_pay=Decimal("0"),
            official_pay=Decimal("0"), self_pay_1=Decimal("95.50"), fund_pay=Decimal("72.50"),
            self_pay_all=Decimal("95.50"), person_count_pay=Decimal("0"), cash_pay=Decimal("95.50")),
        prior_in_scope="527", prior_fund="0"))
    assert res.algorithm_version == ALGORITHM_VERSION
    assert _field(res, "T_FirstPay").calculated_amount == "23"
    assert _field(res, "T_FirstPay").check_status == "matched"
    assert _field(res, "T_BigPay").calculated_amount == "72.50"
    assert _field(res, "T_BigPay").check_status == "matched"
    assert _field(res, "T_BigSelfPay").calculated_amount == "72.50"
    # 居民无补充待遇：not_applicable 且账面为零不冲突
    assert _field(res, "T_BCPay").check_status == "not_applicable"
    assert _field(res, "T_JCPay").check_status == "not_applicable"
    assert _field(res, "T_OfficalPay").check_status == "not_applicable"
    assert _branch(res, "flow.channel_select").outcome == "true"
    # 扩展码候选口径声明始终存在
    assert any(u.code == "CURE_TYPE_EXTENSION_SEMANTICS_UNCONFIRMED" for u in res.uncertainties)
    assert any(u.code == "ROUNDING_RULE_PENDING_CONFIRMATION" for u in res.uncertainties)


def test_prior_accumulation_above_deductible():
    """样本 011100030X240408000002 形态：A=5159>550 → F=0、BigPay=3195×50%。"""
    res = decompose_resident_outpatient(_snapshot(
        items=(_drug_item("3195.00"),),
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("3195"), fee_in=Decimal("3195"), first_pay=Decimal("0"),
            big_pay=Decimal("1597.50"), big_self_pay=Decimal("1597.50")),
        prior_in_scope="5159", prior_fund="2304.50"))
    assert _field(res, "T_FirstPay").calculated_amount == "0"
    assert _field(res, "T_BigPay").calculated_amount == "1597.50"
    assert _field(res, "T_BigPay").check_status == "matched"


def test_cap_clamp():
    """封顶 clamp：prior_fund=4450，cap=4500 → room=50，BigPay=min(B×0.5, 50)。"""
    res = decompose_resident_outpatient(_snapshot(
        items=(_drug_item("1000.00"),),
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("1000"), fee_in=Decimal("1000"), big_pay=Decimal("50.00")),
        prior_in_scope="600", prior_fund="4450"))
    # A=600>550 → F=0；B=1000；raw=500；room=50 → pay=50
    assert _field(res, "T_BigPay").calculated_amount == "50"
    assert _field(res, "T_BigSelfPay").calculated_amount == "950.00"
    assert any(u.code == "BEYOND_CAP_FIELD_ATTRIBUTION_UNCONFIRMED" for u in res.uncertainties)


def test_refund_mirror():
    """退费镜像：样本 011100030X240913000155 形态（退 154）。

    A=695（退前累计）、E=−168 → 区间 [527,695] 起付段 23 → F=−23；B=−145；
    BigPay=clamp(−72.5, −72.5, …)=−72.5。
    """
    res = decompose_resident_outpatient(_snapshot(
        items=(_drug_item("-168.00"),),
        original_trade_no="T000",
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("-168"), fee_in=Decimal("-168"), fee_out=Decimal("0"),
            first_pay=Decimal("-23"), big_pay=Decimal("-72.50"),
            big_self_pay=Decimal("-72.50")),
        prior_in_scope="695", prior_fund="72.50"))
    assert _field(res, "T_FirstPay").calculated_amount == "-23.00"
    assert _field(res, "T_FirstPay").check_status == "matched"
    assert _field(res, "T_BigPay").calculated_amount == "-72.50"
    assert _field(res, "T_BigPay").check_status == "matched"
    assert _branch(res, "flow.refund_check").outcome == "true"


def test_refund_fully_below_deductible():
    """退费全段在起付线下：样本 011100030X240913000046 形态。

    A=389.5、E=−168 → 区间 [221.5,389.5] 全在 550 下 → F=−168、B=0、BigPay=0。
    """
    res = decompose_resident_outpatient(_snapshot(
        items=(_drug_item("-168.00"),),
        original_trade_no="T000",
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("-168"), fee_in=Decimal("-168"), first_pay=Decimal("-168"),
            big_pay=Decimal("0"), big_self_pay=Decimal("0")),
        prior_in_scope="389.50", prior_fund="0"))
    assert _field(res, "T_FirstPay").calculated_amount == "-168.00"
    assert _field(res, "T_BigPay").calculated_amount == "0.00"
    assert _field(res, "T_BigPay").check_status == "matched"


def test_msf_channel():
    """医事服务费通道（17 类）：w0101020010 三级普通 50 元，限额 40 → FeeIn=40、BigPay=40。

    样本 011100030X240913000048 形态；sfxmdj=2 且 zfbl=0 且 xb=40（zfbl=0 不按比例，
    走单价限额分支）。FirstPay=0、BigSelfPay=0、不消费年度累计。
    """
    msf_item = FeeLineItem(
        line_key="0", item_code="w0101020010", catalog_kind=CatalogKind.SERVICE,
        fee=Decimal("50"), fee_occurrence_date=D(2024, 9, 13), item_type="2",
        unit_price=Decimal("50"), count=Decimal("1"),
        fee_in=Decimal("40"), fee_out=Decimal("10"), self_pay_2=Decimal("10"))
    svc_catalog = (ServiceCatalogEntry(
        entry_id="S1", item_code="w0101020010",
        effective_date=D(2017, 4, 8), expiry_date=D(2050, 12, 31),
        sfxmdj="2", self_pay_ratio=Decimal("0"), unit_price_limit=Decimal("40")),)
    snap = _snapshot(
        items=(msf_item,), cure_type="17",
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("50"), fee_in=Decimal("40"), fee_out=Decimal("10"),
            self_pay_2=Decimal("10"), first_pay=Decimal("0"), big_pay=Decimal("40"),
            big_self_pay=Decimal("0"), bc_pay=Decimal("0"), jc_pay=Decimal("0"),
            official_pay=Decimal("0"), self_pay_1=Decimal("0"), fund_pay=Decimal("40"),
            self_pay_all=Decimal("10"), cash_pay=Decimal("10")),
        prior_in_scope="305.50", prior_fund="0",
        # 医事服务费通道不消费累计：口径未确认也不影响
        accumulation_confirmed=False)
    snap = DecompositionSnapshot(
        **{**snap.__dict__, "service_catalog": svc_catalog})
    res = decompose_resident_outpatient(snap)
    assert _field(res, "T_FeeIn").calculated_amount == "40.00"
    assert _field(res, "T_FeeIn").check_status == "matched"
    assert _field(res, "T_FirstPay").calculated_amount == "0"
    assert _field(res, "T_BigPay").calculated_amount == "40.00"
    assert _field(res, "T_BigPay").check_status == "matched"
    assert _field(res, "T_BigSelfPay").calculated_amount == "0"
    assert _branch(res, "msf_pay.settle").outcome == "true"


def test_no_benefit_full_self_pay():
    """无待遇全额自费（ROP-NRB-001）：PN_NoRightReason 非空 → FeeIn=0、FeeOut=全额。"""
    res = decompose_resident_outpatient(_snapshot(
        no_right_reason="5",
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("168"), fee_in=Decimal("0"), fee_out=Decimal("168"),
            self_pay_2=Decimal("0"), first_pay=Decimal("0"), big_pay=Decimal("0"),
            big_self_pay=Decimal("0"), self_pay_1=Decimal("0"), fund_pay=Decimal("0"),
            self_pay_all=Decimal("168"), cash_pay=Decimal("168"))))
    assert res.execution_status == "complete"
    assert _field(res, "T_FeeIn").calculated_amount == "0"
    assert _field(res, "T_FeeIn").check_status == "matched"
    assert _field(res, "T_FeeOut").calculated_amount == "168.00"
    assert _field(res, "T_BigPay").calculated_amount == "0"
    assert _branch(res, "flow.no_benefit_check").outcome == "true"
    assert any(u.code == "NO_BENEFIT_REASON_SEMANTICS_UNCONFIRMED" for u in res.uncertainties)


def test_no_benefit_refund_negative_mirror():
    """无待遇退费（负值镜像）：样本 011100030X240913000039 形态（−180 全自费）。"""
    res = decompose_resident_outpatient(_snapshot(
        items=(_drug_item("-180.00"),),
        no_right_reason="5", original_trade_no="T000",
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("-180"), fee_in=Decimal("0"), fee_out=Decimal("-180"),
            self_pay_2=Decimal("0"), first_pay=Decimal("0"), big_pay=Decimal("0"),
            big_self_pay=Decimal("0"), self_pay_1=Decimal("0"), fund_pay=Decimal("0"),
            self_pay_all=Decimal("-180"), cash_pay=Decimal("-180"))))
    assert _field(res, "T_FeeIn").calculated_amount == "0"
    assert _field(res, "T_FeeOut").calculated_amount == "-180.00"
    assert _field(res, "T_FeeOut").check_status == "matched"


def test_tier1_institution():
    """一级及以下机构档：H_LEVEL='11' → 起付 100、55%。"""
    res = decompose_resident_outpatient(_snapshot(
        items=(_drug_item("1000.00"),), h_level="11",
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("1000"), fee_in=Decimal("1000"), first_pay=Decimal("100"),
            big_pay=Decimal("495.00"), big_self_pay=Decimal("405.00")),
        prior_in_scope="0", prior_fund="0"))
    # A=0 → F=min(1000,100)=100；B=900；BigPay=900×0.55=495
    assert _field(res, "T_FirstPay").calculated_amount == "100"
    assert _field(res, "T_BigPay").calculated_amount == "495.00"
    assert _branch(res, "institution.classify_tier").outcome == "true"


def test_unsupported_profile_not_reusing_resident_formula():
    res = decompose_resident_outpatient(_snapshot(insurance="employee"))
    assert res.execution_status == "unavailable"
    assert res.fields == []
    assert _branch(res, "flow.profile_select").outcome == "not_applicable"
    assert any(u.code == "UNSUPPORTED_PROFILE" for u in res.uncertainties)


def test_unknown_cure_type_channel():
    """未覆盖医疗类别码：目录分解保留，起付/大额不猜测。"""
    res = decompose_resident_outpatient(_snapshot(cure_type="15"))
    assert _branch(res, "flow.channel_select").outcome == "unknown"
    assert any(u.code == "CURE_TYPE_CHANNEL_UNKNOWN" for u in res.uncertainties)
    assert _field(res, "T_FirstPay").check_status == "not_verifiable"
    assert res.execution_status == "partial"


def test_person_type_outside_candidate_still_computes():
    """人员类别不在候选集：声明不确定性但继续计算（2018 起比例与身份无关）。"""
    res = decompose_resident_outpatient(_snapshot(
        person_code="99",
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("168"), fee_in=Decimal("168"), first_pay=Decimal("23"),
            big_pay=Decimal("72.50")),
        prior_in_scope="527", prior_fund="0"))
    assert _branch(res, "person.classify").outcome == "unknown"
    assert any(u.code == "PERSON_TYPE_OUTSIDE_CANDIDATE" for u in res.uncertainties)
    assert _field(res, "T_BigPay").calculated_amount == "72.50"
    assert res.execution_status == "partial"


def test_accumulation_unconfirmed_blocks_deductible():
    """累计口径未确认：起付/大额 unknown，不硬算。"""
    res = decompose_resident_outpatient(_snapshot(
        observed=ObservedSettlementAmounts(fee_all=Decimal("168"), fee_in=Decimal("168")),
        accumulation_confirmed=False))
    assert _field(res, "T_FirstPay").check_status == "not_verifiable"
    assert any(u.code == "PRIOR_ACCUMULATION_CALIBER_UNCONFIRMED" for u in res.uncertainties)


def test_supplement_book_conflict_flagged():
    """居民无补充待遇：账面非零时报资格与账面冲突。"""
    res = decompose_resident_outpatient(_snapshot(
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("168"), fee_in=Decimal("168"), bc_pay=Decimal("10"))))
    f = _field(res, "T_BCPay")
    assert f.check_status == "not_applicable"
    assert f.reason_code == "ELIGIBILITY_CONFLICT_WITH_BOOK"


def test_bigill_channel_after_cap():
    """大病保险通道（ROP-BIGILL-001）：样本 011100030X240914000002 形态。

    门诊大额累计 TB_BigPay=5000≥4500 封顶、救助未支付 → 住院式口径：
    BigillPay=180×0.75=135、FeeOut=Σsp2×0.25=3、SelfPay1=168×0.25=42、SelfPayAll=45。
    """
    items = (
        _drug_item("40.00", key="L1"),
        FeeLineItem(
            line_key="L2", item_code="D002", catalog_kind=CatalogKind.DRUG,
            fee=Decimal("120"), fee_occurrence_date=D(2024, 9, 14), item_type="0",
            unit_price=Decimal("20"), count=Decimal("6"), medic_l=Decimal("0.1"),
            fee_in=Decimal("108"), fee_out=Decimal("12"), self_pay_2=Decimal("12")),
        FeeLineItem(
            line_key="L3", item_code="M001", catalog_kind=CatalogKind.MATERIAL,
            fee=Decimal("20"), fee_occurrence_date=D(2024, 9, 14), item_type="3",
            unit_price=Decimal("5"), count=Decimal("4"),
            fee_in=Decimal("20"), fee_out=Decimal("0"), self_pay_2=Decimal("0")),
    )
    drug_catalog = (
        DrugCatalogEntry(entry_id="E1", item_code="D001",
                         effective_date=D(2024, 1, 1), expiry_date=D(2024, 12, 31),
                         sflb="0101", self_pay_ratio=Decimal("0")),
        DrugCatalogEntry(entry_id="E2", item_code="D002",
                         effective_date=D(2024, 1, 1), expiry_date=D(2024, 12, 31),
                         sflb="0102", self_pay_ratio=Decimal("0.1")),
    )
    mat_catalog = (MaterialCatalogEntry(
        entry_id="M1", item_code="M001",
        effective_date=D(2024, 1, 1), expiry_date=D(2024, 12, 31)),)
    snap = _snapshot(
        items=items,
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("180"), fee_in=Decimal("168"), fee_out=Decimal("3"),
            self_pay_2=Decimal("3"), first_pay=Decimal("0"), big_pay=Decimal("0"),
            big_self_pay=Decimal("0"), bc_pay=Decimal("0"), jc_pay=Decimal("0"),
            official_pay=Decimal("0"), self_pay_1=Decimal("42"), fund_pay=Decimal("135"),
            self_pay_all=Decimal("45"), person_count_pay=Decimal("0"),
            cash_pay=Decimal("45"), bigill_pay=Decimal("135"), civil_pay=Decimal("0")),
        prior_in_scope="176206.15", prior_fund="5000")
    snap = DecompositionSnapshot(
        **{**snap.__dict__, "drug_catalog": drug_catalog, "material_catalog": mat_catalog})
    res = decompose_resident_outpatient(snap)
    assert _branch(res, "flow.bigill_channel_check").outcome == "true"
    assert _field(res, "T_BigillPay").calculated_amount == "135.00"
    assert _field(res, "T_BigillPay").check_status == "matched"
    assert _field(res, "T_FeeOut").calculated_amount == "3.00"
    assert _field(res, "T_FeeOut").check_status == "matched"
    assert _field(res, "T_SelfPay2").calculated_amount == "3.00"
    assert _field(res, "T_BigPay").calculated_amount == "0"
    assert _field(res, "T_FundPay").calculated_amount == "135.00"
    assert _field(res, "T_SelfPay1").calculated_amount == "42.00"
    assert _field(res, "T_SelfPayAll").calculated_amount == "45.00"
    assert any(u.code == "BIGILL_CHANNEL_RULE_CANDIDATE" for u in res.uncertainties)


def test_bigill_channel_refund_mirror():
    """大病通道退费镜像：样本 011100030X240914000003 形态（−180 → BigillPay=−135）。"""
    items = (_drug_item("-180.00", key="L1"),)
    snap = _snapshot(
        items=items, original_trade_no="T000",
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("-180"), fee_in=Decimal("-180"), fee_out=Decimal("0"),
            self_pay_2=Decimal("0"), first_pay=Decimal("0"), big_pay=Decimal("0"),
            big_self_pay=Decimal("0"), self_pay_1=Decimal("-45"), fund_pay=Decimal("-135"),
            self_pay_all=Decimal("-45"), bigill_pay=Decimal("-135"), civil_pay=Decimal("0")),
        prior_in_scope="176374.15", prior_fund="5000")
    res = decompose_resident_outpatient(snap)
    assert _branch(res, "flow.bigill_channel_check").outcome == "true"
    assert _field(res, "T_BigillPay").calculated_amount == "-135.00"
    assert _field(res, "T_BigillPay").check_status == "matched"
    assert _field(res, "T_FundPay").calculated_amount == "-135.00"


def test_civil_pay_channel_marks_not_verifiable():
    """救助渠道（ROP-CIVIL-001）：NT_CivilPay≠0 → FeeOut/SelfPay2/BigSelfPay 不判定对错。"""
    res = decompose_resident_outpatient(_snapshot(
        items=(_drug_item("3133.51"),),
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("3140.30"), fee_in=Decimal("3133.51"), fee_out=Decimal("3.34"),
            self_pay_2=Decimal("3.34"), first_pay=Decimal("0"), big_pay=Decimal("0"),
            big_self_pay=Decimal("0"), self_pay_1=Decimal("1538.60"),
            fund_pay=Decimal("1598.36"), self_pay_all=Decimal("1541.94"),
            cash_pay=Decimal("1541.94"), civil_pay=Decimal("1598.36")),
        prior_in_scope="12931.90", prior_fund="5000"))
    assert _branch(res, "flow.civil_pay_check").outcome == "true"
    assert any(u.code == "CIVIL_PAY_CHANNEL_PRESENT" for u in res.uncertainties)
    # 大额/起付/医保内仍独立核对（不受救助影响）
    assert _field(res, "T_BigPay").check_status == "matched"  # 0=0（封顶 room≤0）
    assert _field(res, "T_FirstPay").check_status == "matched"
    assert _field(res, "T_FeeIn").check_status == "matched"
    # 救助冲抵相关字段不判定对错
    assert _field(res, "T_FeeOut").check_status == "not_verifiable"
    assert _field(res, "T_SelfPay2").check_status == "not_verifiable"
    assert _field(res, "T_BigSelfPay").check_status == "not_verifiable"
    # 大病通道不得误入（救助存在时判定不评估）
    assert _branch(res, "flow.bigill_channel_check").outcome == "not_evaluated"


def test_amount_fields_point_to_their_own_calculation():
    """大额支付只引用基金支付记录，个人差额归大额自付；汇总金额引用目录合计。"""
    from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence

    snap = _snapshot(
        items=(_drug_item("3195.00"),),
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("3435"), fee_in=Decimal("3195"), fee_out=Decimal("240"),
            self_pay_2=Decimal("180"), first_pay=Decimal("0"), big_pay=Decimal("1597.50"),
            big_self_pay=Decimal("1597.50"), self_pay_1=Decimal("1597.50"),
            fund_pay=Decimal("1597.50"), self_pay_all=Decimal("1837.50"),
            person_count_pay=Decimal("0"), cash_pay=Decimal("1837.50")),
        prior_in_scope="5159", prior_fund="2304.50")
    res = attach_evidence(decompose_resident_outpatient(snap), snap)

    assert _field(res, "T_BigPay").calculation_refs == ["calc.big_pay.capped"]
    assert _field(res, "T_BigSelfPay").calculation_refs == ["calc.big_pay.self_pay"]
    assert _field(res, "T_FeeOut").calculation_refs == ["calc.catalog.total_out_scope"]
    assert _field(res, "T_SelfPay2").calculation_refs == ["calc.catalog.total_self_pay_2"]


def test_rule_checks_state_segment_base_and_cap_headroom():
    """条件表给实际事实：本笔基数、封顶已付与剩余额度；未进入的大病分支不称采用。"""
    from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence

    snap = _snapshot(
        items=(_drug_item("3195.00"),),
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("3435"), fee_in=Decimal("3195"), fee_out=Decimal("240"),
            self_pay_2=Decimal("180"), first_pay=Decimal("0"), big_pay=Decimal("1597.50"),
            big_self_pay=Decimal("1597.50"), fund_pay=Decimal("1597.50"),
            self_pay_all=Decimal("1837.50")),
        prior_in_scope="5159", prior_fund="2304.50")
    res = attach_evidence(decompose_resident_outpatient(snap), snap)
    groups = {group.group_id: group for group in res.explanation_evidence.rule_choices}

    rate = next(c for c in groups["rules-ROP-RATE"].candidates if c.status == "selected")
    segment = next(check for check in rate.checks if check.name == "费用分段")
    assert segment.actual == "本笔基数 3195.00 元"
    tier = next(check for check in rate.checks if check.name == "机构等级档")
    assert "机构等级代码 02" in tier.actual

    cap = groups["rules-ROP-CAP"].candidates[0]
    headroom = next(check for check in cap.checks if check.name == "年度封顶额度")
    assert "交易前已支付 2304.50 元" in headroom.actual
    assert "剩余额度 2195.50 元" in headroom.actual
    assert "未触及上限" in headroom.actual

    bigill = groups["rules-ROP-BIGILL"].candidates[0]
    assert bigill.status == "eligible"
    assert "未进入该待遇分支" in bigill.reason


def test_total_and_personal_pay_have_independent_calculation_chain():
    """问总额/个人支付时要有逐行合计与分量计算，不能只剩账面恒等。"""
    res = decompose_resident_outpatient(_snapshot(
        items=(_drug_item("3195.00"),),
        observed=ObservedSettlementAmounts(
            fee_all=Decimal("3435"), fee_in=Decimal("3195"), fee_out=Decimal("240"),
            self_pay_2=Decimal("180"), first_pay=Decimal("0"), big_pay=Decimal("1597.50"),
            big_self_pay=Decimal("1597.50"), self_pay_1=Decimal("1597.50"),
            fund_pay=Decimal("1597.50"), self_pay_all=Decimal("1837.50")),
        prior_in_scope="5159", prior_fund="2304.50"))

    fee_all = _field(res, "T_FeeAll")
    assert fee_all.check_type == "detail_aggregation"
    assert fee_all.calculation_refs == ["calc.catalog.total_fee"]
    self_pay_1 = _field(res, "T_SelfPay1")
    assert self_pay_1.check_type == "independent_recalculation"
    assert "calc.self_pay_1.parts" in self_pay_1.calculation_refs
    self_pay_all = _field(res, "T_SelfPayAll")
    assert self_pay_all.check_type == "independent_recalculation"
    assert self_pay_all.calculation_refs == ["calc.self_pay_all.parts"]
    calc = next(c for c in res.calculations if c.calculation_id == "calc.self_pay_all.parts")
    assert calc.formula_id == "self_pay_all_components_v1"
    assert [op.ref for op in calc.operands] == [
        "calc.deductible.split", "calc.catalog.total_out_scope", "calc.big_pay.self_pay"]


def test_catalog_rule_labels_use_resident_ids_not_employee():
    """居民门诊链复用 split_catalog，但取整规则与目录语义引用编号必须是 ROP-*，不串 EOP-*。"""
    snapshot = replace(_snapshot(), drug_catalog=(DrugCatalogEntry(
        entry_id="E1", item_code="D001",
        effective_date=D(2024, 1, 1), expiry_date=D(2024, 12, 31),
        sflb="0102", self_pay_ratio=Decimal("0.10")),))
    res = decompose_resident_outpatient(snapshot)
    catalog_calcs = [c for c in res.calculations
                     if c.calculation_id.startswith("calc.catalog.self_pay_2")]
    assert catalog_calcs
    for calc in catalog_calcs:
        assert calc.rounding_rule is not None
        assert "ROP-RND-001" in calc.rounding_rule
        assert "EOP" not in calc.rounding_rule
    rule_unc = next(u for u in res.uncertainties
                    if u.code == "CATALOG_RULE_PENDING_OFFICIAL_CONFIRMATION")
    assert "ROP-CAT-000" in rule_unc.message
    assert "EOP" not in rule_unc.message
