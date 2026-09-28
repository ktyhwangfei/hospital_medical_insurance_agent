"""目录分解单元测试（设计 §7.2 / §14 目录与限价矩阵）。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    BranchOutcome,
    CatalogKind,
    DrugCatalogEntry,
    FeeLineItem,
    MaterialCatalogEntry,
    PackagingType,
    RoundingMode,
    ServiceCatalogEntry,
)
from src.runtime.policy_qa.fee_decomposition.catalog_split import split_catalog

MODE = RoundingMode.HALF_UP
D = date
HOSP = "H001"


def _drug_item(**kw) -> FeeLineItem:
    base = dict(
        line_key="L1", item_code="D001", catalog_kind=CatalogKind.DRUG,
        fee=Decimal("100.00"), fee_occurrence_date=D(2024, 5, 1), item_type="0",
        unit_price=Decimal("100.00"), count=Decimal("1"),
    )
    base.update(kw)
    return FeeLineItem(**base)


def _drug_entry(**kw) -> DrugCatalogEntry:
    base = dict(
        entry_id="E1", item_code="D001",
        effective_date=D(2024, 1, 1), expiry_date=D(2024, 12, 31),
        sflb="无自付",
    )
    base.update(kw)
    return DrugCatalogEntry(**base)


def _run(item, entry, kind="drug"):
    kwargs = dict(drug_catalog=(), service_catalog=(), material_catalog=())
    if isinstance(entry, DrugCatalogEntry) or entry is None and kind == "drug":
        kwargs["drug_catalog"] = (entry,) if entry else ()
    elif isinstance(entry, ServiceCatalogEntry):
        kwargs["service_catalog"] = (entry,)
    elif isinstance(entry, MaterialCatalogEntry):
        kwargs["material_catalog"] = (entry,)
    return split_catalog((item,), rounding_mode=MODE, hospital_code=HOSP, **kwargs)


def _branch(res, step_suffix: str):
    for b in res.branches:
        if b.step_id.endswith(step_suffix):
            return b
    raise AssertionError(f"branch {step_suffix} not found: {[b.step_id for b in res.branches]}")


# ── 药品：甲乙丙（无自付/有自付/全自付） ──


def test_drug_no_self_pay_full_in_scope():
    res = _run(_drug_item(), _drug_entry())
    line = res.lines[0]
    assert line.status == BranchOutcome.TRUE
    assert line.in_scope == Decimal("100.00") and line.out_scope == Decimal("0")
    assert res.is_complete and res.total_in_scope == Decimal("100.00")


def test_drug_partial_self_pay_excluded_from_in_scope():
    # 有自付 10%：先行自付不进报销基数（FeeIn=Fee-自付二）且计入医保外（决策记录 D14，账面实证）
    res = _run(_drug_item(), _drug_entry(sflb="有自付", self_pay_ratio=Decimal("0.10")))
    line = res.lines[0]
    assert line.in_scope == Decimal("90.00")
    assert line.out_scope == Decimal("10.00")
    assert line.self_pay_2 == Decimal("10.00")
    assert "partial_self_pay" in line.labels


def test_drug_full_self_pay_out_of_scope():
    res = _run(_drug_item(), _drug_entry(sflb="全自付"))
    line = res.lines[0]
    assert line.in_scope == Decimal("0") and line.out_scope == Decimal("100.00")


def test_drug_fee_type_conflict_stays_unknown():
    res = _run(_drug_item(fee_type="全自付"), _drug_entry(sflb="无自付"))
    assert res.lines[0].status == BranchOutcome.UNKNOWN
    assert _branch(res, "class_conflict").reason_code == "CLASSIFICATION_CONFLICT"


# ── 目录匹配：无命中/多命中/生效失效边界/空截止日期 ──


def test_missing_catalog_not_first_match():
    res = _run(_drug_item(item_code="NOPE"), _drug_entry())
    b = _branch(res, "L1")
    assert b.outcome == BranchOutcome.FALSE and b.reason_code == "MISSING_CATALOG"
    assert res.lines[0].status == BranchOutcome.UNKNOWN
    assert not res.is_complete and res.total_in_scope is None


def test_ambiguous_catalog_not_first_match():
    e2 = DrugCatalogEntry(entry_id="E2", item_code="D001",
                          effective_date=D(2024, 3, 1), expiry_date=D(2024, 12, 31), sflb="全自付")
    res = split_catalog((_drug_item(),), (_drug_entry(), e2), (), (), HOSP, MODE)
    b = _branch(res, "L1")
    assert b.outcome == BranchOutcome.UNKNOWN and b.reason_code == "AMBIGUOUS_CATALOG"
    assert res.lines[0].status == BranchOutcome.UNKNOWN


def test_catalog_effective_expiry_boundary_inclusive():
    # 生效日当日命中；失效日当日仍有效；失效日后一日无命中
    entry = _drug_entry(effective_date=D(2024, 5, 1), expiry_date=D(2024, 5, 10))
    assert _run(_drug_item(fee_occurrence_date=D(2024, 5, 1)), entry).lines[0].status == BranchOutcome.TRUE
    assert _run(_drug_item(fee_occurrence_date=D(2024, 5, 10)), entry).lines[0].status == BranchOutcome.TRUE
    res = _run(_drug_item(fee_occurrence_date=D(2024, 5, 11)), entry)
    assert _branch(res, "L1").reason_code == "MISSING_CATALOG"


def test_open_ended_entry_does_not_mask_potential_ambiguity():
    # 1 条确定命中 + 1 条空截止日期条目：空截止不默认永久有效（设计 §5.3），
    # 空截止条目可能同样适用 → 潜在多命中，不得按唯一命中放行
    open_entry = DrugCatalogEntry(entry_id="E2", item_code="D001",
                                  effective_date=D(2024, 1, 1), expiry_date=None, sflb="全自付")
    res = split_catalog((_drug_item(),), (_drug_entry(), open_entry), (), (), HOSP, MODE)
    b = _branch(res, "L1")
    assert b.outcome == BranchOutcome.UNKNOWN and b.reason_code == "CATALOG_VALIDITY_UNKNOWN"
    assert res.lines[0].status == BranchOutcome.UNKNOWN


def test_catalog_open_expiry_not_treated_as_permanent():
    # 空结束日期不默认永久有效（设计 §5.3）
    res = _run(_drug_item(), _drug_entry(expiry_date=None))
    b = _branch(res, "L1")
    assert b.outcome == BranchOutcome.UNKNOWN and b.reason_code == "CATALOG_VALIDITY_UNKNOWN"


# ── 自制剂 ──


def test_preparation_in_hospital_within_standard_price():
    entry = _drug_entry(ypfl="16", bzjg=Decimal("100.00"), preparation_hospital_code=HOSP,
                        sflb="无自付")
    res = _run(_drug_item(unit_price=Decimal("100.00")), entry)
    assert res.lines[0].in_scope == Decimal("100.00")


def test_preparation_over_standard_price_full_self_pay():
    entry = _drug_entry(ypfl="16", bzjg=Decimal("50.00"), preparation_hospital_code=HOSP)
    res = _run(_drug_item(unit_price=Decimal("60.00")), entry)
    line = res.lines[0]
    assert line.out_scope == Decimal("100.00") and line.in_scope == Decimal("0")
    assert "preparation_over_price" in line.labels


def test_preparation_used_outside_hospital_full_self_pay():
    entry = _drug_entry(ypfl="6", bzjg=Decimal("100.00"), preparation_hospital_code="H999")
    res = _run(_drug_item(), entry)
    assert res.lines[0].out_scope == Decimal("100.00")


def test_preparation_ncp_overlap_unknown():
    entry = _drug_entry(ypfl="16", a_ypbs=True, a_mzxj=Decimal("100.00"),
                        bzjg=Decimal("100.00"), preparation_hospital_code=HOSP)
    res = _run(_drug_item(), entry)
    assert res.lines[0].status == BranchOutcome.UNKNOWN
    assert _branch(res, "preparation_ncp_overlap.L1").reason_code == "PREPARATION_NCP_OVERLAP_UNCONFIRMED"


# ── 集采限价 ──


def test_ncp_within_limit_normal_division():
    entry = _drug_entry(a_ypbs=True, a_mzxj=Decimal("100.00"), sflb="无自付")
    res = _run(_drug_item(unit_price=Decimal("100.00")), entry)
    assert _branch(res, "ncp_price.L1").outcome == BranchOutcome.TRUE
    assert "centralized_procurement" in res.lines[0].labels
    assert res.lines[0].in_scope == Decimal("100.00")


def test_ncp_over_limit_unknown_no_formula():
    # a_xbbl 语义未确认 → unknown，不编码公式
    entry = _drug_entry(a_ypbs=True, a_mzxj=Decimal("50.00"))
    res = _run(_drug_item(unit_price=Decimal("60.00")), entry)
    assert res.lines[0].status == BranchOutcome.UNKNOWN
    assert _branch(res, "ncp_price.L1").outcome == BranchOutcome.FALSE
    assert any(u.code == "NCP_EXCESS_RATIO_SEMANTICS_UNCONFIRMED" for u in res.uncertainties)


def test_ncp_unappraised_branch_unknown():
    entry = _drug_entry(a_ypbs=True, a_mzxj=Decimal("50.00"))
    res = _run(_drug_item(unit_price=Decimal("60.00"), consistency_evaluation_passed=False), entry)
    assert any(u.code == "NCP_UNAPPRAISED_RULE_UNCONFIRMED" for u in res.uncertainties)


def test_ncp_split_pack_uses_unit_limit():
    entry = _drug_entry(a_ypbs=True, a_mzxj=Decimal("10.00"), ncp_unit_limit=Decimal("100.00"))
    # 拆包按制剂单位限价比价：60 ≤ 100 → 限价内
    res = _run(_drug_item(unit_price=Decimal("60.00"), packaging_type=PackagingType.SPLIT_PACK), entry)
    assert _branch(res, "ncp_price.L1").outcome == BranchOutcome.TRUE
    # 未给包装类型默认整包：60 > 10 → 超限价 unknown
    res2 = _run(_drug_item(unit_price=Decimal("60.00")), entry)
    assert _branch(res2, "ncp_price.L1").outcome == BranchOutcome.FALSE


# ── 诊疗/服务设施 ──


def _service_item(**kw) -> FeeLineItem:
    base = dict(
        line_key="S1", item_code="X001", catalog_kind=CatalogKind.SERVICE,
        fee=Decimal("200.00"), fee_occurrence_date=D(2024, 5, 1), item_type="1",
        unit_price=Decimal("200.00"), count=Decimal("1"),
    )
    base.update(kw)
    return FeeLineItem(**base)


def _service_entry(**kw) -> ServiceCatalogEntry:
    base = dict(entry_id="SE1", item_code="X001",
                effective_date=D(2024, 1, 1), expiry_date=D(2024, 12, 31))
    base.update(kw)
    return ServiceCatalogEntry(**base)


def test_service_sfxmdj_levels():
    assert _run(_service_item(), _service_entry(sfxmdj="1")).lines[0].in_scope == Decimal("200.00")
    assert _run(_service_item(), _service_entry(sfxmdj="3")).lines[0].out_scope == Decimal("200.00")
    r2 = _run(_service_item(), _service_entry(sfxmdj="2", self_pay_ratio=Decimal("0.20")))
    assert r2.lines[0].self_pay_2 == Decimal("40.00")


def test_service_sfxmdj_empty_must_be_unknown():
    res = _run(_service_item(), _service_entry(sfxmdj=None))
    assert res.lines[0].status == BranchOutcome.UNKNOWN
    assert _branch(res, "service_class.S1").reason_code == "SFXMDJ_EMPTY"


def test_service_unit_price_limit_excess_to_self_pay_2():
    # 单价限额 150，单价 200 ×1 → 超出 50 入自付二
    res = _run(_service_item(), _service_entry(sfxmdj="2", unit_price_limit=Decimal("150.00")))
    assert res.lines[0].self_pay_2 == Decimal("50.00")


def test_service_partial_without_ratio_or_limit_unknown():
    res = _run(_service_item(), _service_entry(sfxmdj="2"))
    assert res.lines[0].status == BranchOutcome.UNKNOWN
    assert _branch(res, "service_ratio.S1").reason_code == "SELF_PAY_RULE_PARAM_MISSING"


def test_check_fee_rule_gated_unknown():
    # EOP-CAT-008 生效日期未明确且待官方核证 → 不静默生效
    res = _run(_service_item(is_check_fee=True), _service_entry(sfxmdj="1"))
    assert res.lines[0].status == BranchOutcome.UNKNOWN
    assert _branch(res, "check_fee_param.S1").reason_code == "PARAM_EFFECTIVE_DATE_UNCLEAR"


# ── 医用材料 ──


def _material_item(**kw) -> FeeLineItem:
    base = dict(
        line_key="M1", item_code="M001", catalog_kind=CatalogKind.MATERIAL,
        fee=Decimal("1000.00"), fee_occurrence_date=D(2024, 5, 1),
        unit_price=Decimal("1000.00"), count=Decimal("1"),
    )
    base.update(kw)
    return FeeLineItem(**base)


def _material_entry(**kw) -> MaterialCatalogEntry:
    base = dict(entry_id="ME1", item_code="M001",
                effective_date=D(2020, 1, 1), expiry_date=D(2030, 12, 31))
    base.update(kw)
    return MaterialCatalogEntry(**base)


def test_material_below_1000_fully_included():
    res = _run(_material_item(fee=Decimal("999.00"), unit_price=Decimal("999.00")), _material_entry())
    assert res.lines[0].in_scope == Decimal("999.00")


def test_material_ge_1000_included_80pct():
    res = _run(_material_item(), _material_entry())  # 单价 1000，2024 费用发生
    line = res.lines[0]
    assert line.in_scope == Decimal("800.00") and line.self_pay_2 == Decimal("200.00")
    assert "material_threshold" in line.labels


def test_material_historical_500_tier_by_fee_date():
    # 费用发生日期 2022：≥500 按 70% 纳入
    res = _run(_material_item(fee_occurrence_date=D(2022, 6, 1)), _material_entry())
    assert res.lines[0].in_scope == Decimal("700.00")
    # 费用发生日期 2005：≥500 按 50% 纳入
    res2 = _run(_material_item(fee_occurrence_date=D(2005, 6, 1)),
                _material_entry(effective_date=D(2000, 1, 1)))
    assert res2.lines[0].in_scope == Decimal("500.00")


def test_material_artificial_organ_exception_unknown():
    res = _run(_material_item(), _material_entry(is_artificial_organ=True))
    assert res.lines[0].status == BranchOutcome.UNKNOWN
    assert _branch(res, "material_exception.M1").reason_code == "MATERIAL_EXCEPTION_POLICY_NOT_COVERED"


def test_cross_year_items_use_own_versions():
    # 跨年：同一笔交易两条材料明细按各自费用发生日期选版本（600 元单价）
    i1 = _material_item(line_key="M1", fee=Decimal("600.00"), unit_price=Decimal("600.00"),
                        fee_occurrence_date=D(2022, 12, 30))
    i2 = _material_item(line_key="M2", fee=Decimal("600.00"), unit_price=Decimal("600.00"),
                        fee_occurrence_date=D(2023, 1, 5))
    entry = _material_entry()
    res = split_catalog((i1, i2), (), (), (entry,), HOSP, MODE)
    by_key = {ln.line_key: ln for ln in res.lines}
    assert by_key["M1"].in_scope == Decimal("420.00")  # 2022 档 70%
    assert by_key["M2"].in_scope == Decimal("600.00")  # 2023 档 <1000 全额


# ── 数据边界 ──


def test_fee_quantity_mismatch_flagged_but_fee_kept():
    res = _run(_drug_item(fee=Decimal("95.00"), unit_price=Decimal("100.00"), count=Decimal("1")),
               _drug_entry())
    b = _branch(res, "fee_quantity_check.L1")
    assert b.outcome == BranchOutcome.FALSE and b.reason_code == "FEE_QUANTITY_MISMATCH"
    assert res.lines[0].in_scope == Decimal("95.00")  # 不用单价×数量替代账面 Fee


def test_duplicate_line_keys_fatal():
    items = (_drug_item(), _drug_item())  # 同 line_key
    res = split_catalog(items, (_drug_entry(),), (), (), HOSP, MODE)
    assert res.fatal_issue == "DUPLICATE_LINE_KEY"
    assert res.lines == () and not res.is_complete
