"""批量评估实证决策（D1-D20）内核级回归测试。

决策依据与回退方式：docs/superpowers/specs/2026-09-29-issue78-批量评估决策与待确认.md
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    AnnualAccumulation,
    BranchOutcome,
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
from src.runtime.policy_qa.fee_decomposition.catalog_split import split_catalog
from src.runtime.policy_qa.fee_decomposition.employee_outpatient import (
    classify_institution,
    decompose_employee_outpatient,
)

MODE = RoundingMode.HALF_UP
D = date
HOSP = "01110003"


def _item(**kw) -> FeeLineItem:
    base = dict(
        line_key="L1", item_code="D001", catalog_kind=CatalogKind.DRUG,
        fee=Decimal("100.00"), fee_occurrence_date=D(2024, 5, 1), item_type="0",
        unit_price=Decimal("100.00"), count=Decimal("1"),
    )
    base.update(kw)
    return FeeLineItem(**base)


def _drug(**kw) -> DrugCatalogEntry:
    base = dict(
        entry_id="E1", item_code="D001",
        effective_date=D(2024, 1, 1), expiry_date=D(2024, 12, 31),
        sflb="0101",
    )
    base.update(kw)
    return DrugCatalogEntry(**base)


def _run(item, entry):
    return split_catalog(
        (item,), drug_catalog=(entry,), service_catalog=(), material_catalog=(),
        rounding_mode=MODE, hospital_code=HOSP,
    )


# ── D2 收费类别码（flid=230）→ 自付档 ──


def test_d2_fee_category_codes_classification():
    # 甲类 0101 无自付
    assert _run(_item(), _drug(sflb="0101")).lines[0].in_scope == Decimal("100.00")
    # 其它类 0103 全自付
    res = _run(_item(), _drug(sflb="0103"))
    assert res.lines[0].in_scope == Decimal("0") and res.lines[0].out_scope == Decimal("100.00")
    # 乙类 0102 有自付按目录 zfbl
    res = _run(_item(), _drug(sflb="0102", self_pay_ratio=Decimal("0.10")))
    assert res.lines[0].self_pay_2 == Decimal("10.00")
    # 未覆盖码（如 0204 民族药）不猜测 → unknown
    assert _run(_item(), _drug(sflb="0204")).lines[0].status == BranchOutcome.UNKNOWN


def test_d2_group_conflict_only_across_groups():
    # 同组不同码（目录 0101 vs 账面 FeeType 0201 均甲类）不冲突
    res = _run(_item(fee_type="0201"), _drug(sflb="0101"))
    assert res.lines[0].status == BranchOutcome.TRUE
    # 跨组（目录甲类 vs 账面乙类）停未知
    res = _run(_item(fee_type="0102"), _drug(sflb="0101"))
    assert res.lines[0].status == BranchOutcome.UNKNOWN
    assert any(b.reason_code == "CLASSIFICATION_CONFLICT" for b in res.branches)


# ── D14 先行自付不进报销基数、计入医保外 ──


def test_d14_partial_self_pay_out_of_in_scope():
    res = _run(_item(), _drug(sflb="0102", self_pay_ratio=Decimal("0.10")))
    line = res.lines[0]
    assert line.in_scope == Decimal("90.00")
    assert line.out_scope == Decimal("10.00")
    assert line.self_pay_2 == Decimal("10.00")


# ── D18 明细行 MEDIC_L>0 优先于目录 zfbl ──


def test_d18_medic_l_overrides_catalog_ratio():
    res = _run(_item(medic_l=Decimal("0.20")), _drug(sflb="0102", self_pay_ratio=Decimal("0.10")))
    line = res.lines[0]
    assert line.self_pay_2 == Decimal("20.00")
    assert line.in_scope == Decimal("80.00")
    # MEDIC_L=0 视为未维护，回落目录 zfbl
    res = _run(_item(medic_l=Decimal("0")), _drug(sflb="0102", self_pay_ratio=Decimal("0.10")))
    assert res.lines[0].self_pay_2 == Decimal("10.00")


# ── D17 非集采门诊限价：超限全自担、限内按比例 ──


def test_d17_price_limit_from_line_sp_scale():
    # 账面样本 XA10BDX252：fee=1000，SP_SCALE=177.90，MEDIC_L=0.1 → in=160.11
    res = _run(
        _item(fee=Decimal("1000.00"), unit_price=Decimal("1000.00"),
              sp_scale=Decimal("177.90"), medic_l=Decimal("0.10")),
        _drug(sflb="0102", self_pay_ratio=Decimal("0.10"), a_mzxj=Decimal("177.90")),
    )
    line = res.lines[0]
    assert line.in_scope == Decimal("160.11")
    assert line.self_pay_2 == Decimal("839.89")
    assert line.out_scope == Decimal("839.89")


def test_d17_price_limit_from_catalog_when_line_missing():
    res = _run(
        _item(fee=Decimal("1000.00"), unit_price=Decimal("1000.00")),
        _drug(sflb="0102", self_pay_ratio=Decimal("0.10"), a_mzxj=Decimal("177.90")),
    )
    assert res.lines[0].in_scope == Decimal("160.11")


# ── D19 集采超限价：最终自付比例（a_xbbl/MEDIC_L） ──


def test_d19_ncp_excess_final_ratio():
    # 账面样本 XL01BAP030：fee=3000（单价 1000>限价 809），a_xbbl=0.2 → sp2=600
    res = _run(
        _item(fee=Decimal("3000.00"), unit_price=Decimal("1000.00"), count=Decimal("3"),
              medic_l=Decimal("0.20")),
        _drug(sflb="0102", self_pay_ratio=Decimal("0.10"),
              a_ypbs=True, a_mzxj=Decimal("809.00"), a_xbbl=Decimal("0.20")),
    )
    line = res.lines[0]
    assert line.self_pay_2 == Decimal("600.00")
    assert line.in_scope == Decimal("2400.00")
    assert any(u.code == "NCP_EXCESS_RULE_CANDIDATE" for u in res.uncertainties)


def test_d19_ncp_within_limit_normal_division():
    res = _run(
        _item(fee=Decimal("500.00"), unit_price=Decimal("500.00")),
        _drug(sflb="0102", self_pay_ratio=Decimal("0.10"),
              a_ypbs=True, a_mzxj=Decimal("809.00"), a_xbbl=Decimal("0.20")),
    )
    line = res.lines[0]
    assert line.self_pay_2 == Decimal("50.00")
    assert line.in_scope == Decimal("450.00")


# ── D20 全自付行不评估自制剂分支 ──


def test_d20_full_self_pay_skips_preparation_gate():
    # 账面样本 J110101009860030：ypfl=16 自制剂候选，但 sflb=0103 全自付 → 直接整行自费
    res = _run(
        _item(fee=Decimal("27.48"), unit_price=Decimal("27.48")),
        _drug(sflb="0103", self_pay_ratio=Decimal("1.00"), ypfl="16", bzjg=Decimal("0.00")),
    )
    line = res.lines[0]
    assert line.status == BranchOutcome.TRUE
    assert line.in_scope == Decimal("0") and line.out_scope == Decimal("27.48")


# ── D9 机构分类：H_TYPE 主依据 ──


def test_d9_institution_h_type_primary():
    kind, _ = classify_institution("02", "01")
    assert kind.value == "other"
    kind, _ = classify_institution("14", "04")
    assert kind.value == "community"
    # H_TYPE 缺失回落 H_LEVEL：14 实测为未评级 → 未知（S1「14=社区」假设已废弃）
    kind, _ = classify_institution("14", None)
    assert kind.value == "unknown"
    kind, _ = classify_institution("02", None)
    assert kind.value == "other"


# ── D15 无待遇全额自费分支 ──


def _snapshot_no_benefit() -> DecompositionSnapshot:
    obs = ObservedSettlementAmounts(
        fee_all=Decimal("250.00"), fee_in=Decimal("0.00"), fee_out=Decimal("250.00"),
        self_pay_2=Decimal("0.00"), first_pay=Decimal("0.00"), big_pay=Decimal("0.00"),
        big_self_pay=Decimal("0.00"), bc_pay=Decimal("0.00"), jc_pay=Decimal("0.00"),
        official_pay=Decimal("0.00"), self_pay_1=Decimal("0.00"), fund_pay=Decimal("0.00"),
        self_pay_all=Decimal("250.00"), person_count_pay=Decimal("0.00"),
        cash_pay=Decimal("250.00"),
    )
    return DecompositionSnapshot(
        settlement_ref="settlement:T-NB",
        insurance_type="employee", medical_category="outpatient",
        trade=TradeAnchor(trade_no="T-NB", trade_date=D(2024, 9, 13),
                          hospital_code=HOSP, no_right_reason="4"),
        person=PersonProfile(person_type_code="11", birth_date=D(1980, 1, 1)),
        institution=InstitutionProfile(hospital_code=HOSP, h_level="02", h_type="01"),
        accumulation=AnnualAccumulation(prior_in_scope_fee=Decimal("0.00"),
                                        prior_in_scope_fee_is_pre_trade=True),
        items=(
            FeeLineItem(line_key="L1", item_code="D001", catalog_kind=CatalogKind.DRUG,
                        fee=Decimal("250.00"), fee_occurrence_date=D(2024, 9, 13),
                        item_type="0", unit_price=Decimal("250.00"), count=Decimal("1")),
        ),
        observed=obs,
        rounding_mode=MODE,
    )


def test_d15_no_benefit_trade_all_personal():
    result = decompose_employee_outpatient(_snapshot_no_benefit())
    fields = {f.field_code: f for f in result.fields}
    assert fields["T_FeeIn"].calculated_amount == "0"
    assert fields["T_FeeIn"].check_status == "matched"
    assert fields["T_FeeOut"].calculated_amount == "250.00"
    assert fields["T_FirstPay"].calculated_amount == "0"
    assert fields["T_BigPay"].calculated_amount == "0"
    assert any(u.code == "NO_BENEFIT_REASON_SEMANTICS_UNCONFIRMED" for u in result.uncertainties)
    # 无待遇原因码未命中时走正常流程
    normal = _snapshot_no_benefit()
    normal = replace(normal, trade=TradeAnchor(
        trade_no="T-NB2", trade_date=D(2024, 9, 13), hospital_code=HOSP,
    ))
    result2 = decompose_employee_outpatient(normal)
    assert not any(u.code == "NO_BENEFIT_REASON_SEMANTICS_UNCONFIRMED" for u in result2.uncertainties)
