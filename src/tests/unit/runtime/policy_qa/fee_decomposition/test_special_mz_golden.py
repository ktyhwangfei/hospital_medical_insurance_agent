"""职工门特·按项目付费（Issue #79，门诊套表）黄金样本核对测试。

样本来源：bjyb 库 yb_brdjxx(yllb='12')/yb_mzjyxx(fyfs='0')/yb_mzfymx 真实结算
（djh=567/609/675/708/814 及 2025 年 5 笔），手工核对记录见
docs/superpowers/specs/2026-09-30-issue79-门特按项目付费-验证记录.md。

口径声明：
- 周期上下文按 yb_dyxxtsb/yb_dyxxnd 交易后快照−本笔账面推导注入（confirmed）；
- 资格字段按 Issue #79 候选口径映射（cjjrdj→等级组、gwydybz→公疗资格、cblb=61→社会化）；
- 取整模式显式 RoundingMode.HALF_UP（ESP-RND-001 待确认，属假定口径）；
- 分段坐标守卫（segment_coordinate_guard）：坐标未确认时统筹/大额 not_verifiable。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.adapters.data_supply.outpatient_special_mz_queries import (
    derive_mz_cycle_context,
    map_civil_medical_eligible,
    map_military_grade,
)
from src.domain.insurance.fee_decomposition import (
    OutpatientSpecialSnapshot,
    RoundingMode,
    SpecialCycleContext,
    SpecialFeeLineItem,
    SpecialInstitutionProfile,
    SpecialObservedAmounts,
    SpecialPersonProfile,
)
from src.runtime.policy_qa.fee_decomposition.employee_outpatient_special import (
    decompose_employee_outpatient_special,
)

MODE = RoundingMode.HALF_UP
D = date
HOSP = "01110003"  # 协和 H_LEVEL='02' → 三级


def _item(line_key: str, fee: str, in_scope: str, out_scope: str,
          advance: str = "0", fee_date: date = D(2024, 9, 19)) -> SpecialFeeLineItem:
    return SpecialFeeLineItem(
        line_key=line_key, item_code=f"X{line_key}", fee=Decimal(fee),
        in_scope_fee=Decimal(in_scope), out_scope_fee=Decimal(out_scope),
        full_self_pay_advance=Decimal(advance), fee_date=fee_date,
    )


def _snapshot(
    *,
    djh: str,
    cblb: str,
    settle_date: date,
    items: tuple[SpecialFeeLineItem, ...],
    observed: SpecialObservedAmounts,
    cycle: SpecialCycleContext,
    retirement_category: str | None = None,
    military_grade: str | None = None,
    military_grade_raw: str | None = None,
    civil_medical_eligible: bool | None = None,
    allow_observed_deductible: bool = False,
    segment_coordinate_guard: bool = True,
) -> OutpatientSpecialSnapshot:
    return OutpatientSpecialSnapshot(
        settlement_ref=f"special_mz:djh={djh}",
        insurance_type="employee", medical_category="outpatient_special",
        djh=djh, settle_date=settle_date, admit_date=settle_date,
        yllb="12", fund_type="3",
        person=SpecialPersonProfile(
            cblb=cblb, birth_date=D(1952, 4, 1), special_record_start=D(2024, 9, 19),
            retirement_category=retirement_category,
            military_grade=military_grade, military_grade_raw=military_grade_raw,
            civil_medical_eligible=civil_medical_eligible),
        institution=SpecialInstitutionProfile(hospital_code=HOSP, h_level="02"),
        cycle=cycle, items=items, observed=observed, rounding_mode=MODE,
        allow_observed_deductible=allow_observed_deductible,
        segment_coordinate_guard=segment_coordinate_guard,
    )


def _fields(result) -> dict:
    return {f.field_code: f for f in result.fields}


def _assert_all_matched(result, codes) -> None:
    fields = _fields(result)
    for code in codes:
        assert fields[code].check_status in ("matched", "not_applicable"), (
            f"{code}: {fields[code].check_status} "
            f"账={fields[code].observed_amount} 算={fields[code].calculated_amount}")


ALL_FUND_FIELDS = ("ZJE", "YBN", "YBW", "GRZIFTW", "YBNQFJE", "TCZHF", "TCZIF",
                   "DEGWYZHF", "DEGWYZIF", "BCZHF", "JCZHF", "GFYLBCHBX")


# ── djh=567：退休，军残 1-4 级，年度第 1 周期起付 1300，三级退休 91% ──


def _snapshot_djh567() -> OutpatientSpecialSnapshot:
    return _snapshot(
        djh="567", cblb="21", settle_date=D(2024, 4, 30),
        items=(_item("1", "6000.00", "6000.00", "0.00", fee_date=D(2024, 4, 30)),),
        observed=SpecialObservedAmounts(
            zje=Decimal("6000.00"), ybn=Decimal("6000.00"), ybw=Decimal("0.00"),
            ybnqfje=Decimal("1300.00"), tczhf=Decimal("4277.00"), tczif=Decimal("423.00"),
            degwyzhf=Decimal("0.00"), degwyzif=Decimal("0.00"),
            bczhf=Decimal("211.50"), jczhf=Decimal("1511.50"), gfylbchbx=Decimal("0.00"),
            xjzf=Decimal("0.00"), zhzf=Decimal("0.00"), grziftw=Decimal("0.00")),
        cycle=SpecialCycleContext(
            deductible_standard=Decimal("1300"), prior_cycle_deductible_paid=Decimal("0"),
            prior_annual_pool_fund_payment=Decimal("0"),
            prior_annual_large_fund_payment=Decimal("0"),
            prior_cycle_in_scope_total=Decimal("0"),
            evidence_status="confirmed"),
        retirement_category="normal", military_grade="1-4", military_grade_raw="1",
        civil_medical_eligible=False,
    )


def test_golden_djh567_retired_military_grade14_full_cover():
    result = decompose_employee_outpatient_special(_snapshot_djh567())
    fields = _fields(result)
    _assert_all_matched(result, ALL_FUND_FIELDS)
    # 军残 1-4 级退休：起付 100% + 剩余自付 100%（1300 + (423-211.5) = 1511.50）
    assert fields["JCZHF"].calculated_amount == "1511.50"
    # 现金恒等式：全额基金支付，个人 0
    assert fields["XJZF.identity"].check_status == "matched"


# ── djh=609：退休，军残 5-6 级 + 公疗（585=1300×(95%-50%)） ──


def _snapshot_djh609() -> OutpatientSpecialSnapshot:
    return _snapshot(
        djh="609", cblb="21", settle_date=D(2024, 9, 19),
        items=(_item("1", "1520.00", "1520.00", "0.00"),),
        observed=SpecialObservedAmounts(
            zje=Decimal("1520.00"), ybn=Decimal("1520.00"), ybw=Decimal("0.00"),
            ybnqfje=Decimal("1300.00"), tczhf=Decimal("200.20"), tczif=Decimal("19.80"),
            degwyzhf=Decimal("0.00"), degwyzif=Decimal("0.00"),
            bczhf=Decimal("9.90"), jczhf=Decimal("654.95"), gfylbchbx=Decimal("585.00"),
            xjzf=Decimal("68.85"), zhzf=Decimal("0.00"), grziftw=Decimal("0.00")),
        cycle=SpecialCycleContext(
            deductible_standard=Decimal("1300"), prior_cycle_deductible_paid=Decimal("0"),
            prior_annual_pool_fund_payment=Decimal("10.40"),
            prior_annual_large_fund_payment=Decimal("0"),
            prior_cycle_in_scope_total=Decimal("6"),
            evidence_status="confirmed"),
        retirement_category="normal", military_grade="5-6", military_grade_raw="5",
        civil_medical_eligible=True,
    )


def test_golden_djh609_retired_military_grade56_with_pmed():
    result = decompose_employee_outpatient_special(_snapshot_djh609())
    fields = _fields(result)
    _assert_all_matched(result, ALL_FUND_FIELDS)
    # 军残 5-6 级退休：起付 50% + 剩余自付 50%（650 + 4.95 = 654.95）
    assert fields["JCZHF"].calculated_amount == "654.95"
    # 公疗：起付线以下 1300×(95%-50%)=585；以上 220×97%-…+1300×50% = -1.55 → 0
    assert fields["GFYLBCHBX"].calculated_amount == "585.00"


# ── djh=675：退休，无军残 + 公疗（账面 gfylbchbx=0 但现金证明补助 683.99） ──


def _snapshot_djh675() -> OutpatientSpecialSnapshot:
    return _snapshot(
        djh="675", cblb="21", settle_date=D(2024, 9, 24),
        items=(_item("1", "5083.00", "5083.00", "0.00", fee_date=D(2024, 9, 24)),),
        observed=SpecialObservedAmounts(
            zje=Decimal("5083.00"), ybn=Decimal("5083.00"), ybw=Decimal("0.00"),
            ybnqfje=Decimal("650.00"), tczhf=Decimal("4034.03"), tczif=Decimal("398.97"),
            degwyzhf=Decimal("0.00"), degwyzif=Decimal("0.00"),
            bczhf=Decimal("199.49"), jczhf=Decimal("0.00"), gfylbchbx=Decimal("0.00"),
            xjzf=Decimal("165.49"), zhzf=Decimal("0.00"), grziftw=Decimal("0.00")),
        cycle=SpecialCycleContext(
            deductible_standard=Decimal("650"), prior_cycle_deductible_paid=Decimal("0"),
            prior_annual_pool_fund_payment=Decimal("7917.00"),
            prior_annual_large_fund_payment=Decimal("0"),
            prior_cycle_in_scope_total=Decimal("0"),
            evidence_status="confirmed"),
        retirement_category="normal", military_grade=None, military_grade_raw="0",
        civil_medical_eligible=True,
    )


def test_golden_djh675_pmed_computed_book_field_defect():
    result = decompose_employee_outpatient_special(_snapshot_djh675())
    fields = _fields(result)
    # 公疗：起付线以下 650×95%=617.50 + 以上 max(0, 4433×97%-4034.03-199.49)=66.49 → 683.99
    assert fields["GFYLBCHBX"].calculated_amount == "683.99"
    # 账面 gfylbchbx=0 为记录缺陷（现金 165.49=650×5%+4433×3% 证明补助实际发生）→ 差异保留
    assert fields["GFYLBCHBX"].check_status == "mismatched"
    # 其余 11 个费用分解字段全部吻合
    _assert_all_matched(result, tuple(c for c in ALL_FUND_FIELDS if c != "GFYLBCHBX"))


# ── djh=708：社会化退休（cblb=61 → prepaid），统筹段退休补助 50% ──


def _snapshot_djh708() -> OutpatientSpecialSnapshot:
    return _snapshot(
        djh="708", cblb="61", settle_date=D(2024, 9, 3),
        items=(_item("1", "1518.00", "1518.00", "0.00", fee_date=D(2024, 9, 3)),),
        observed=SpecialObservedAmounts(
            zje=Decimal("1518.00"), ybn=Decimal("1518.00"), ybw=Decimal("0.00"),
            ybnqfje=Decimal("0.00"), tczhf=Decimal("1381.38"), tczif=Decimal("136.62"),
            degwyzhf=Decimal("0.00"), degwyzif=Decimal("0.00"),
            bczhf=Decimal("68.31"), jczhf=Decimal("0.00"), gfylbchbx=Decimal("0.00"),
            xjzf=Decimal("45.54"), zhzf=Decimal("0.00"), grziftw=Decimal("0.00")),
        cycle=SpecialCycleContext(
            deductible_standard=Decimal("1300"), prior_cycle_deductible_paid=Decimal("1300"),
            prior_annual_pool_fund_payment=Decimal("8294.66"),
            prior_annual_large_fund_payment=Decimal("0"),
            prior_cycle_in_scope_total=Decimal("9906.52"),
            evidence_status="confirmed"),
        retirement_category="prepaid", military_grade=None, military_grade_raw="0",
        civil_medical_eligible=False,
    )


def test_golden_djh708_prepaid_retired_pool_supplement_50pct():
    result = decompose_employee_outpatient_special(_snapshot_djh708())
    fields = _fields(result)
    _assert_all_matched(result, ALL_FUND_FIELDS)
    # 社会化退休统筹共付段补充保险 50%（ESP-RSUP-003）：136.62×0.5=68.31
    assert fields["BCZHF"].calculated_amount == "68.31"


# ── djh=814：交易前年度统筹累计已达 10 万封顶 → 全额大额 80%（退休） ──


def _snapshot_djh814() -> OutpatientSpecialSnapshot:
    return _snapshot(
        djh="814", cblb="21", settle_date=D(2024, 10, 20),
        items=(_item("1", "1050.00", "1050.00", "0.00", fee_date=D(2024, 10, 20)),),
        observed=SpecialObservedAmounts(
            zje=Decimal("1050.00"), ybn=Decimal("1050.00"), ybw=Decimal("0.00"),
            ybnqfje=Decimal("0.00"), tczhf=Decimal("0.00"), tczif=Decimal("0.00"),
            degwyzhf=Decimal("840.00"), degwyzif=Decimal("210.00"),
            bczhf=Decimal("105.00"), jczhf=Decimal("52.50"), gfylbchbx=Decimal("0.00"),
            xjzf=Decimal("15.75"), zhzf=Decimal("0.00"), grziftw=Decimal("0.00")),
        cycle=SpecialCycleContext(
            deductible_standard=Decimal("1300"), prior_cycle_deductible_paid=Decimal("1300"),
            prior_annual_pool_fund_payment=Decimal("100000"),
            prior_annual_large_fund_payment=Decimal("131532.90"),
            prior_cycle_in_scope_total=Decimal("36071.18"),
            evidence_status="confirmed"),
        retirement_category="normal", military_grade="5-6", military_grade_raw="5",
        civil_medical_eligible=False,
    )


def test_golden_djh814_pool_cap_reached_all_in_large():
    result = decompose_employee_outpatient_special(_snapshot_djh814())
    fields = _fields(result)
    _assert_all_matched(result, ALL_FUND_FIELDS)
    # 大额退休 80%（ESP-LGP-003）：1050×0.8=840；退休补助大额段 50%；军残大额剩余 50%
    assert fields["DEGWYZHF"].calculated_amount == "840.00"
    assert fields["BCZHF"].calculated_amount == "105.00"
    assert fields["JCZHF"].calculated_amount == "52.50"


# ── 2025 样本：分段坐标不可得 → 守卫触发，统筹/大额 not_verifiable ──


def _snapshot_2025_unknown_cycle() -> OutpatientSpecialSnapshot:
    return _snapshot(
        djh="1937487", cblb="11", settle_date=D(2025, 6, 12),
        items=(_item("1", "7500.00", "6750.00", "750.00", advance="750.00",
                     fee_date=D(2025, 6, 12)),),
        observed=SpecialObservedAmounts(
            zje=Decimal("7500.00"), ybn=Decimal("6750.00"), ybw=Decimal("750.00"),
            ybnqfje=Decimal("0.00"), tczhf=Decimal("6412.50"), tczif=Decimal("337.50"),
            degwyzhf=Decimal("0.00"), degwyzif=Decimal("0.00"),
            bczhf=Decimal("0.00"), jczhf=Decimal("0.00"), gfylbchbx=Decimal("0.00"),
            xjzf=Decimal("1087.50"), zhzf=Decimal("0.00"), grziftw=Decimal("750.00")),
        cycle=SpecialCycleContext(evidence_status="unknown",
                                  evidence_note="dyxxtsb/dyxxnd 无本笔行"),
        military_grade=None, military_grade_raw="0", civil_medical_eligible=False,
        allow_observed_deductible=True,
    )


def test_unknown_cycle_segment_guard_not_verifiable():
    result = decompose_employee_outpatient_special(_snapshot_2025_unknown_cycle())
    fields = _fields(result)
    # 起付：账面 0 作条件输入（勾稽级）→ matched
    assert fields["YBNQFJE"].check_status == "matched"
    # 分段坐标不可证明 → 统筹/大额 not_verifiable（不按坐标下界硬算 85%）
    for code in ("TCZHF", "TCZIF", "DEGWYZHF", "DEGWYZIF"):
        assert fields[code].check_status == "not_verifiable"
        assert fields[code].reason_code == "SEGMENT_COORDINATE_UNDERDETERMINED"
    # 资格驱动零值字段仍可判定：在职无退休补助、无军残、不享受公疗
    for code in ("BCZHF", "JCZHF", "GFYLBCHBX"):
        assert fields[code].check_status in ("matched", "not_applicable")
    codes = {u.code for u in result.uncertainties}
    assert "SEGMENT_COORDINATE_UNDERDETERMINED" in codes


def test_guard_off_lower_bound_computation_preserved():
    """守卫关闭时保持坐标下界计算（zy 套表评估口径行为不变）。"""
    snapshot = _snapshot_2025_unknown_cycle()
    from dataclasses import replace
    snapshot = replace(snapshot, segment_coordinate_guard=False)
    result = decompose_employee_outpatient_special(snapshot)
    fields = _fields(result)
    # 下界 C0=0 → 三级在职 85%：6750×0.85=5737.50（与账面 95% 档 6412.50 差异如实呈现）
    assert fields["TCZHF"].calculated_amount == "5737.50"
    assert fields["TCZHF"].check_status == "mismatched"


# ── derive_mz_cycle_context 纯函数 ──


def test_derive_cycle_context_confirmed_from_post_trade_snapshot():
    settle = {"tsbybn": Decimal("506.00"), "ybnqfje": Decimal("0.00"),
              "tczhf": Decimal("460.46"), "degwyzhf": Decimal("0.00")}
    cycle_row = {"bqqfje": Decimal("1300.00"), "bqljybnje": Decimal("10578.00")}
    annual_row = {"bnzqslj": 1, "bntczfje": Decimal("8819.58"), "bndezfje": Decimal("0.00")}
    ctx, notes = derive_mz_cycle_context(cycle_row, annual_row, settle,
                                         special_record_start=D(2024, 4, 30),
                                         settle_date=D(2024, 4, 30))
    assert ctx.evidence_status == "confirmed"
    assert ctx.deductible_standard == Decimal("1300")  # bnzqslj=1 → 首周期
    assert ctx.prior_cycle_deductible_paid == Decimal("1300.00")
    assert ctx.prior_cycle_in_scope_total == Decimal("10072.00")
    assert ctx.prior_annual_pool_fund_payment == Decimal("8359.12")
    assert any("CYCLE_INDEX_FROM_TBQSRQ" in n for n in notes)


def test_derive_cycle_context_second_cycle_standard_650():
    settle = {"tsbybn": Decimal("5083.00"), "ybnqfje": Decimal("650.00"),
              "tczhf": Decimal("4034.03"), "degwyzhf": Decimal("0.00")}
    cycle_row = {"bqqfje": Decimal("650.00"), "bqljybnje": Decimal("5083.00")}
    annual_row = {"bnzqslj": 2, "bntczfje": Decimal("11951.03"), "bndezfje": Decimal("0.00")}
    ctx, _ = derive_mz_cycle_context(cycle_row, annual_row, settle,
                                     special_record_start=D(2024, 9, 24),
                                     settle_date=D(2024, 9, 24))
    assert ctx.evidence_status == "confirmed"
    assert ctx.deductible_standard == Decimal("650")  # bnzqslj=2 → 第二及以后周期
    assert ctx.prior_cycle_deductible_paid == Decimal("0.00")


def test_derive_cycle_context_missing_rows_unknown():
    ctx, notes = derive_mz_cycle_context(None, None, {}, special_record_start=D(2024, 9, 3),
                                         settle_date=D(2025, 9, 23))
    assert ctx.evidence_status == "unknown"
    # tsbqsrq=2024-09-03 + 360 天 → 2025-09-23 落在第 2 个周期
    assert any("第 2 个门特结算周期" in n for n in notes)


def test_derive_cycle_context_negative_derivation_unknown():
    settle = {"tsbybn": Decimal("9999.00"), "ybnqfje": Decimal("0.00"),
              "tczhf": Decimal("0.00"), "degwyzhf": Decimal("0.00")}
    cycle_row = {"bqqfje": Decimal("0.00"), "bqljybnje": Decimal("100.00")}
    annual_row = {"bnzqslj": 1, "bntczfje": Decimal("0.00"), "bndezfje": Decimal("0.00")}
    ctx, notes = derive_mz_cycle_context(cycle_row, annual_row, settle,
                                         special_record_start=None, settle_date=D(2024, 1, 1))
    assert ctx.evidence_status == "unknown"
    assert any("CYCLE_DERIVATION_CONTRADICTION" in n for n in notes)


# ── 资格字段映射 ──


def test_map_military_grade_value_domain():
    assert map_military_grade("1") == ("1-4", "1", None)
    assert map_military_grade("4")[0] == "1-4"
    assert map_military_grade("5") == ("5-6", "5", None)
    assert map_military_grade("6")[0] == "5-6"
    assert map_military_grade("0") == (None, "0", None)
    assert map_military_grade(None) == (None, None, None)
    grade, raw, note = map_military_grade("9")
    assert grade is None and raw == "9" and note is not None


def test_map_civil_medical_eligible_value_domain():
    assert map_civil_medical_eligible(0) == (True, None)
    assert map_civil_medical_eligible(1) == (False, None)
    eligible, note = map_civil_medical_eligible(None)
    assert eligible is None and note is not None
