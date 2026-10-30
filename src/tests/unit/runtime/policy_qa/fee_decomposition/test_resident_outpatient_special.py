"""城乡居民门特（按项目付费）内核单元测试（Issue #81）。

golden 形态取自 bjybdb 真实登记（688 培美曲塞+他克莫司、718 滞后年度表、
690 全甲类；探查记录见 scripts/eval/issue81_data_probe*.py）。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    CatalogKind,
    DrugCatalogEntry,
    FeeLineItem,
    MaterialCatalogEntry,
    OutpatientSpecialSnapshot,
    RoundingMode,
    ServiceCatalogEntry,
    SpecialCycleContext,
    SpecialFeeLineItem,
    SpecialInstitutionProfile,
    SpecialObservedAmounts,
    SpecialPersonProfile,
    SecondaryCoverageContext,
)
from src.runtime.policy_qa.fee_decomposition.resident_outpatient_special import (
    ALGORITHM_VERSION,
    decompose_resident_outpatient_special,
)
from src.runtime.policy_qa.fee_decomposition.resident_special_catalog import (
    split_special_mz_catalog,
)

D = date
MODE = RoundingMode.HALF_UP


def _items() -> tuple[SpecialFeeLineItem, ...]:
    """688 明细形态：培美曲塞 699（乙类 0.1）+ 他克莫司 488（乙类但 zfbl=0）。"""
    return (
        SpecialFeeLineItem(
            line_key="1", item_code="D001", fee=Decimal("699"), item_name="培美曲塞",
            sflb="0102", self_pay_level="2",
            in_scope_fee=Decimal("629.10"), out_scope_fee=Decimal("69.90"),
            full_self_pay_advance=Decimal("69.90"),
            unit_price=Decimal("233"), quantity=Decimal("3"), fee_date=D(2024, 9, 25)),
        SpecialFeeLineItem(
            line_key="2", item_code="D002", fee=Decimal("488"), item_name="他克莫司",
            sflb="0102", self_pay_level="1",
            in_scope_fee=Decimal("488"), out_scope_fee=Decimal("0"),
            full_self_pay_advance=Decimal("0"),
            unit_price=Decimal("122"), quantity=Decimal("4"), fee_date=D(2024, 9, 25)),
    )


def _catalog_items() -> tuple[FeeLineItem, ...]:
    return (
        FeeLineItem(
            line_key="1", item_code="D001", catalog_kind=CatalogKind.DRUG,
            fee=Decimal("699"), fee_occurrence_date=D(2024, 9, 25), item_type="0",
            fee_type="0102", unit_price=Decimal("233"), count=Decimal("3"),
            fee_in=Decimal("629.10"), fee_out=Decimal("69.90"), self_pay_2=Decimal("69.90")),
        FeeLineItem(
            line_key="2", item_code="D002", catalog_kind=CatalogKind.DRUG,
            fee=Decimal("488"), fee_occurrence_date=D(2024, 9, 25), item_type="0",
            fee_type="0102", unit_price=Decimal("122"), count=Decimal("4"),
            fee_in=Decimal("488"), fee_out=Decimal("0"), self_pay_2=Decimal("0")),
    )


def _drug_catalog() -> tuple[DrugCatalogEntry, ...]:
    """688 两个项目的目录条目。

    集采标识与门诊限价取真实库实测值（2026-10-26 只读查询 yb_ypzdml）：
    培美曲塞 `A_ypbs=1`、`A_mzxj=809`（高于本单单价 233，限价内不改变拆分）；
    他克莫司 `A_ypbs=0`。两个条目的集采标识均为已识别值（0/1），
    夹具必须带 `a_ypbs_known=True`（缺省 False=未确认会让条目判定路径留 unknown，
    与真实数据不符，且金额不变）。
    """
    return (
        DrugCatalogEntry(entry_id="E1", item_code="D001",
                         effective_date=D(2024, 1, 1), expiry_date=D(2024, 12, 31),
                         sflb="0102", self_pay_ratio=Decimal("0.1"), special_disease_marker="2",
                         a_ypbs=True, a_ypbs_known=True, a_ypbs_raw="1",
                         a_mzxj=Decimal("809")),
        DrugCatalogEntry(entry_id="E2", item_code="D002",
                         effective_date=D(2024, 1, 1), expiry_date=D(2024, 12, 31),
                         sflb="0102", self_pay_ratio=Decimal("0"), special_disease_marker="494",
                         a_ypbs=False, a_ypbs_known=True, a_ypbs_raw="0"),
    )


def _split():
    return split_special_mz_catalog(
        _catalog_items(), _drug_catalog(), (), (), "01110003", MODE)


def _snapshot(
    items=None,
    observed: SpecialObservedAmounts | None = None,
    insurance="resident", category="outpatient_special",
    cblb="70", h_level="02",
    cycle: SpecialCycleContext | None = None,
) -> OutpatientSpecialSnapshot:
    return OutpatientSpecialSnapshot(
        settlement_ref="special_mz_settlement:688",
        insurance_type=insurance, medical_category=category,
        djh="688", settle_date=D(2024, 9, 25), admit_date=D(2024, 1, 1),
        yllb="12", fund_type="93",
        person=SpecialPersonProfile(cblb=cblb, birth_date=D(1955, 1, 1), civil_type="25"),
        institution=SpecialInstitutionProfile(hospital_code="01110003", h_level=h_level),
        cycle=cycle or SpecialCycleContext(
            deductible_standard=None,
            prior_cycle_deductible_paid=Decimal("1300"),
            prior_annual_pool_fund_payment=Decimal("0"),
            prior_annual_large_fund_payment=Decimal("51981.75"),
            prior_cycle_in_scope_total=Decimal("70000"),
            cycle_position="first",
            evidence_status="confirmed",
            evidence_note="dyxxtsb/dyxxnd 推导"),
        items=items or _items(),
        observed=observed or SpecialObservedAmounts(
            zje=Decimal("1187"), ybn=Decimal("1117.10"), ybw=Decimal("69.90"),
            ybnqfje=Decimal("0"), tczhf=Decimal("0"), tczif=Decimal("0"),
            degwyzhf=Decimal("837.83"), degwyzif=Decimal("279.27"),
            bczhf=Decimal("0"), jczhf=Decimal("0"), gfylbchbx=Decimal("0"),
            xjzf=Decimal("0"), zhzf=Decimal("0"), grziftw=Decimal("69.90"),
            big_ill_pay=Decimal("226.96"), feein_db_pay=Decimal("181.53"), feeout_db_pay=Decimal("45.43"),
            civil_in=Decimal("122.21"), feein_maf_pay=Decimal("97.74"), feeout_maf_pay=Decimal("24.47"),
            retire_officer_pay=Decimal("0")),
        rounding_mode=MODE,
        secondary_coverage=SecondaryCoverageContext(Decimal("23491.42"), Decimal("16878.30"), True, "confirmed"),
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


def test_golden_688_complete_all_matched():
    """djh=688 golden：目录分解 1117.10/69.90、起付 0（已交满 1300）、大病 837.83。"""
    res = decompose_resident_outpatient_special(_snapshot(), _split())
    assert res.algorithm_version == ALGORITHM_VERSION
    assert res.execution_status == "complete"
    assert _field(res, "TSBYBN").calculated_amount == "1117.10"
    assert _field(res, "TSBYBN").check_status == "matched"
    assert _field(res, "TSBYBW").calculated_amount == "69.90"
    assert _field(res, "GRZIFTW").calculated_amount == "69.90"
    assert _field(res, "YBNQFJE").calculated_amount == "0"
    assert _field(res, "YBNQFJE").check_status == "matched"
    # 大病：base=1117.10×0.75=837.825 → HALF_UP 837.83（实证支持取整口径）
    assert _field(res, "DEGWYZHF").calculated_amount == "837.83"
    assert _field(res, "DEGWYZHF").check_status == "matched"
    assert _field(res, "DEGWYZIF").calculated_amount == "279.27"
    for code, expected in (("FEEOUT_DB_PAY", "45.43"), ("BIG_ILL_PAY", "226.96"),
                           ("FEEOUT_MAF_PAY", "24.47"), ("CIVIL_IN", "122.21"), ("PERSON_PAYABLE", "0")):
        field = _field(res, code)
        assert Decimal(field.calculated_amount) == Decimal(expected)
        assert field.check_status == "matched"
    assert _field(res, "TCZHF").calculated_amount is None
    assert _field(res, "TCZHF").check_status == "not_applicable"
    assert _field(res, "TCZHF").reason_code == "RESIDENT_SPECIAL_NO_POOL"
    assert _field(res, "BCZHF").check_status == "not_applicable"
    assert _branch(res, "pool.not_applicable").outcome == "true"
    assert any(u.code == "ROUNDING_RULE_PENDING_CONFIRMATION" for u in res.uncertainties)


def test_688_public_and_model_use_the_same_book_settlement_amounts():
    import json
    from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence
    from src.runtime.policy_qa.fee_decomposition.model_explanation import build_model_input
    from src.runtime.policy_qa.fee_decomposition.public_view import build_public_view_dict
    from src.runtime.policy_qa.public_contract import FeeDecompositionPublic

    snapshot = _snapshot()
    result = decompose_resident_outpatient_special(snapshot, _split())
    public = build_public_view_dict(attach_evidence(result, snapshot), summary_text="", summary_source="template")
    fields = {field["field_code"]: field for field in public["fields"]}
    for code in ("FEEOUT_DB_PAY", "BIG_ILL_PAY", "CIVIL_IN", "PERSON_PAYABLE"):
        assert fields[code]["explainable"] is True
        assert Decimal(fields[code]["observed_amount"]) == Decimal(fields[code]["calculated_amount"])
    adopted = next(calc for calc in public["calculations"] if calc["calculation_id"] == "calc.secondary.feeout_db_pay")
    assert adopted["unrounded_result"] is None
    assert adopted["rounding_rule"] == "按本单结算金额"
    assert adopted["formula"] == "大病支付（医保外）：按本单结算记录采用 45.43 元"
    assert any(node["name"] == "按比例先行自付的大病支付" and node["source"] == "本笔结算记录"
               and Decimal(node["value"]) == Decimal("45.43") for node in public["formula_inputs"])
    payload = build_model_input(FeeDecompositionPublic.model_validate(public), "为什么个人支付0元？")
    for encoded in (json.dumps(public, ensure_ascii=False), payload.model_dump_json()):
        assert '"45.44"' not in encoded
        assert '"226.97"' not in encoded
        assert '"122.20"' not in encoded
        assert '"24.46"' not in encoded
    payable = next(calc for calc in payload.decomposition.calculations if calc.calculation_id == "calc.secondary.person_payable")
    assert [Decimal(op.value) for op in payable.operands][-2:] == [Decimal("226.96"), Decimal("122.21")]


def test_deductible_already_paid_in_cycle():
    """周期内已交满起付（1300≥1300）→ 本次起付 0；学生儿童档标准 650。"""
    snap = _snapshot(cblb="15")
    res = decompose_resident_outpatient_special(snap, _split())
    assert _field(res, "YBNQFJE").calculated_amount == "0"
    assert _field(res, "DEGWYZHF").calculated_amount == "837.83"


def test_deductible_partial_when_cycle_not_filled():
    """周期内已交 800 → 本次起付 min(1117.10, 1300−800)=500；大病=(1117.10−500)×0.75。"""
    snap = _snapshot(cycle=SpecialCycleContext(
        deductible_standard=None,
        prior_cycle_deductible_paid=Decimal("800"),
        prior_annual_pool_fund_payment=Decimal("0"),
        prior_annual_large_fund_payment=Decimal("1000"),
        prior_cycle_in_scope_total=Decimal("70000"),
        cycle_position="first", evidence_status="confirmed", evidence_note="t"))
    res = decompose_resident_outpatient_special(snap, _split())
    assert _field(res, "YBNQFJE").calculated_amount == "500"
    # base=617.10×0.75=462.825 → HALF_UP 462.83
    assert _field(res, "DEGWYZHF").calculated_amount == "462.83"
    assert _field(res, "DEGWYZIF").calculated_amount == "154.27"


def test_tier2_institution_rate_78():
    """二级机构档：大病 78%。"""
    snap = _snapshot(h_level="07")
    res = decompose_resident_outpatient_special(snap, _split())
    # 起付 800 档已交 1300≥800 → 0；base=1117.10×0.78=871.338 → 871.34
    assert _field(res, "DEGWYZHF").calculated_amount == "871.34"


def test_cap_clamp():
    """年度大额累计 249999 → room=1，degwyzhf=clamp(837.83, …, 1)=1。"""
    snap = _snapshot(cycle=SpecialCycleContext(
        deductible_standard=None,
        prior_cycle_deductible_paid=Decimal("1300"),
        prior_annual_pool_fund_payment=Decimal("0"),
        prior_annual_large_fund_payment=Decimal("249999"),
        prior_cycle_in_scope_total=Decimal("70000"),
        cycle_position="first", evidence_status="confirmed", evidence_note="t"))
    res = decompose_resident_outpatient_special(snap, _split())
    assert _field(res, "DEGWYZHF").calculated_amount == "1"
    assert _field(res, "DEGWYZIF").calculated_amount == "1116.10"


def test_cycle_evidence_unknown_blocks():
    """周期证据 unknown → 起付/大病 not_verifiable，不硬算。"""
    snap = _snapshot(cycle=SpecialCycleContext(evidence_status="unknown",
                                               evidence_note="无周期行"))
    res = decompose_resident_outpatient_special(snap, _split())
    assert _field(res, "YBNQFJE").check_status == "not_verifiable"
    assert _field(res, "DEGWYZHF").check_status == "not_verifiable"
    assert res.execution_status == "partial"
    assert any(u.code == "CYCLE_EVIDENCE_NOT_CONFIRMED" for u in res.uncertainties)


def test_unsupported_profile():
    res = decompose_resident_outpatient_special(
        _snapshot(insurance="employee"), _split())
    assert res.execution_status == "unavailable"
    assert _branch(res, "flow.profile_select").outcome == "not_applicable"
    assert any(u.code == "UNSUPPORTED_PROFILE" for u in res.uncertainties)


def test_negative_amount_blocked():
    bad_item = SpecialFeeLineItem(
        line_key="1", item_code="D001", fee=Decimal("-100"), fee_date=D(2024, 9, 25))
    res = decompose_resident_outpatient_special(
        _snapshot(items=(bad_item,)), _split())
    assert res.execution_status == "unavailable"
    assert any(u.code == "UNSUPPORTED_REVERSAL_OR_NEGATIVE" for u in res.uncertainties)


def test_duplicate_line_key_blocked():
    dup = (
        SpecialFeeLineItem(line_key="1", item_code="D001", fee=Decimal("100"),
                           fee_date=D(2024, 9, 25)),
        SpecialFeeLineItem(line_key="1", item_code="D002", fee=Decimal("50"),
                           fee_date=D(2024, 9, 25)),
    )
    res = decompose_resident_outpatient_special(_snapshot(items=dup), _split())
    assert res.execution_status == "unavailable"
    assert any(u.code == "DUPLICATE_LINE_KEY" for u in res.uncertainties)


def test_supplement_book_conflict_flagged():
    snap = _snapshot(observed=SpecialObservedAmounts(
        zje=Decimal("1187"), ybn=Decimal("1117.10"), ybw=Decimal("69.90"),
        ybnqfje=Decimal("0"), bczhf=Decimal("10")))
    res = decompose_resident_outpatient_special(snap, _split())
    f = _field(res, "BCZHF")
    assert f.check_status == "not_applicable"
    assert f.reason_code == "ELIGIBILITY_CONFLICT_WITH_BOOK"


def test_self_pay_1_is_computed_for_project_fee_method():
    """项目付费单 grzif1 列在已核样本中未维护：自付一按起付+统筹自付+大额自付计算，
    observed=None 诚实降级 not_verifiable，不作账面核对。"""
    snapshot = _snapshot()
    result = decompose_resident_outpatient_special(snapshot, _split())
    field = next(f for f in result.fields if f.field_code == "GRZIF1")
    assert field.label == "个人支付自付（一）金额"
    assert field.check_type == "independent_recalculation"
    assert field.check_status == "not_verifiable"
    assert field.observed_amount is None
    assert field.reason_code == "SELF_PAY_1_BOOK_COLUMN_UNMAINTAINED"
    expected = sum(v for v in (snapshot.observed.ybnqfje, snapshot.observed.degwyzif) if v is not None)
    assert field.calculated_amount is not None
    assert Decimal(field.calculated_amount) == expected
    calc = next(c for c in result.calculations if c.calculation_id == "calc.self_pay_1.parts")
    assert calc.formula_id == "self_pay_1_components_v1"
    assert Decimal(calc.result) == expected
    assert calc.calculation_id in field.calculation_refs


def test_self_pay_1_summary_does_not_claim_book_amount():
    """公开 summary：GRZIF1 不得虚称"结算记录 X 元"，须表达"列未维护、分量计算、不作账面核对"。"""
    from src.runtime.policy_qa.fee_decomposition.public_view import render_summary

    result = decompose_resident_outpatient_special(_snapshot(), _split())
    text = render_summary(result)
    line = next(ln for ln in text.split("\n") if "自付（一）金额" in ln)
    assert "结算记录" not in line
    assert "无此列" not in line
    assert "未维护" in line
    assert "不作账面核对" in line
