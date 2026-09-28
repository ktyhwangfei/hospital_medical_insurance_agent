"""职工门特（门诊特殊病）黄金样本核对测试（Issue #78 第二流程）。

样本来源：docs/superpowers/specs/issue78-职工门特-手算样例.md
（bjyb 住院套表真实结算，djh=604/707/705，逐行明细与结算表核对一致）。

口径声明：
- 周期上下文按 evidence_status="confirmed" 注入（手算样例已核实第几周期/已交起付），
  验证内核独立重算与账面一致；评估口径假定值（assumed/observed_book）另有 fail-closed 用例。
- 取整模式显式 RoundingMode.HALF_UP（ESP-RND-001 待确认，属假定口径）。
- 参数引用 ESP-RSUP-001/002 remark 实测记录：djh=705/707 bczhf=统筹自付×50% 吻合。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

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
HOSP = "01110003"


def _item(line_key: str, fee: str, in_scope: str, out_scope: str,
          advance: str = "0", fee_date: date = D(2024, 9, 3)) -> SpecialFeeLineItem:
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
    insurance_type: str = "employee",
    medical_category: str = "outpatient_special",
    allow_observed_deductible: bool = False,
) -> OutpatientSpecialSnapshot:
    return OutpatientSpecialSnapshot(
        settlement_ref=f"special:djh={djh}",
        insurance_type=insurance_type, medical_category=medical_category,
        djh=djh, settle_date=settle_date, admit_date=D(2024, 9, 2),
        yllb="16", fund_type="3",
        person=SpecialPersonProfile(cblb=cblb, birth_date=D(1953, 1, 1),
                                    retirement_category=retirement_category),
        institution=SpecialInstitutionProfile(hospital_code=HOSP, h_level="02"),  # 三级
        cycle=cycle, items=items, observed=observed, rounding_mode=MODE,
        allow_observed_deductible=allow_observed_deductible,
    )


def _fields(result) -> dict:
    return {f.field_code: f for f in result.fields}


# ── 例 1：djh=604 —— 在职，年度第 2 周期起付 650，三级 85% ──


def _snapshot_djh604() -> OutpatientSpecialSnapshot:
    items = (
        _item("1", "3200.00", "2880.00", "320.00", advance="320.00"),  # 复方阿胶浆
        _item("2", "2230.00", "2007.00", "223.00", advance="223.00"),  # 注射用培美曲塞二钠
    )
    observed = SpecialObservedAmounts(
        zje=Decimal("5430.00"), ybn=Decimal("4887.00"), ybw=Decimal("543.00"),
        ybnqfje=Decimal("650.00"), tczhf=Decimal("3601.45"), tczif=Decimal("635.55"),
        degwyzhf=Decimal("0.00"), degwyzif=Decimal("0.00"),
        bczhf=Decimal("0.00"), jczhf=Decimal("0.00"), gfylbchbx=Decimal("0.00"),
        grziftw=Decimal("543.00"),
    )
    cycle = SpecialCycleContext(
        deductible_standard=Decimal("1300"), prior_cycle_deductible_paid=Decimal("650"),
        evidence_status="confirmed",
        evidence_note="手算样例：年度第 2 个结算周期，起付已交 650",
    )
    return _snapshot(djh="604", cblb="11", settle_date=D(2024, 9, 18),
                     items=items, observed=observed, cycle=cycle)


def test_golden_djh604_employed_second_cycle():
    result = decompose_employee_outpatient_special(_snapshot_djh604())
    fields = _fields(result)
    # 明细汇总与账面一致
    assert fields["ZJE"].check_status == "matched"
    assert fields["YBN"].check_status == "matched"     # 4887.00
    assert fields["YBW"].check_status == "matched"     # 543.00
    assert fields["GRZIFTW"].check_status == "matched"  # 543.00
    # 起付 F = min(4887, max(1300-650, 0)) = 650
    assert fields["YBNQFJE"].calculated_amount == "650"
    assert fields["YBNQFJE"].check_status == "matched"
    # 统筹：B=4237，三级 seg1 在职自付 15% → 4237×85%=3601.45
    assert fields["TCZHF"].calculated_amount == "3601.45"
    assert fields["TCZHF"].check_status == "matched"
    assert fields["TCZIF"].calculated_amount == "635.55"
    assert fields["TCZIF"].check_status == "matched"
    # 未超统筹封顶 → 大额 0
    assert fields["DEGWYZHF"].calculated_amount == "0"
    assert fields["DEGWYZHF"].check_status == "matched"
    # 在职：退休补助不适用，账面 0 无冲突
    assert fields["BCZHF"].check_status == "not_applicable"
    assert fields["BCZHF"].reason_code == "NOT_RETIRED"
    # 取整规则待确认的全局不确定性如实保留
    assert any(u.code == "ROUNDING_RULE_PENDING_CONFIRMATION" for u in result.uncertainties)


# ── 例 2：djh=707 —— 退休，起付已承担，三级退休 91%（全医保内） ──


def _snapshot_djh707() -> OutpatientSpecialSnapshot:
    items = (
        _item("1", "3936.00", "3936.00", "0.00", fee_date=D(2024, 9, 24)),  # 他克莫司胶囊
    )
    observed = SpecialObservedAmounts(
        zje=Decimal("3936.00"), ybn=Decimal("3936.00"), ybw=Decimal("0.00"),
        ybnqfje=Decimal("0.00"), tczhf=Decimal("3581.76"), tczif=Decimal("354.24"),
        degwyzhf=Decimal("0.00"), degwyzif=Decimal("0.00"),
        bczhf=Decimal("177.12"),  # ESP-RSUP-001 remark：djh=707 实测吻合
        jczhf=Decimal("0.00"), gfylbchbx=Decimal("0.00"),
        grziftw=Decimal("0.00"),
    )
    cycle = SpecialCycleContext(
        deductible_standard=Decimal("1300"), prior_cycle_deductible_paid=Decimal("1300"),
        evidence_status="confirmed",
        evidence_note="手算样例：年度内门特起付已承担，本次 F=0",
    )
    return _snapshot(djh="707", cblb="21", settle_date=D(2024, 9, 26),
                     items=items, observed=observed, cycle=cycle,
                     retirement_category="normal")


def test_golden_djh707_retired_no_deductible():
    result = decompose_employee_outpatient_special(_snapshot_djh707())
    fields = _fields(result)
    assert fields["YBN"].check_status == "matched"  # 3936.00
    # F = min(3936, max(1300-1300, 0)) = 0
    assert fields["YBNQFJE"].calculated_amount == "0"
    assert fields["YBNQFJE"].check_status == "matched"
    # 退休自付 = 15%×60% = 9% → 统筹 = 3936×91% = 3581.76
    assert fields["TCZHF"].calculated_amount == "3581.76"
    assert fields["TCZHF"].check_status == "matched"
    assert fields["TCZIF"].calculated_amount == "354.24"
    assert fields["TCZIF"].check_status == "matched"
    # 退休补助 = 统筹自付×50% = 354.24×0.5 = 177.12（ESP-RSUP-001）
    assert fields["BCZHF"].calculated_amount == "177.12"
    assert fields["BCZHF"].check_status == "matched"


# ── 例 3：djh=705 —— 退休，医保内外混合 18 行明细 ──


def _snapshot_djh705() -> OutpatientSpecialSnapshot:
    fd = D(2024, 9, 2)
    items = (
        _item("1", "30.00", "30.00", "0.00", fee_date=fd),          # 项针治疗
        _item("2", "80.00", "73.60", "6.40", "6.40", fd),          # 细菌抗体测定
        _item("3", "50.00", "0.00", "50.00", fee_date=fd),         # 普通视力检查
        _item("4", "50.00", "0.00", "50.00", fee_date=fd),         # 牙再植术
        _item("5", "150.00", "0.00", "150.00", fee_date=fd),       # 局部浸润麻醉
        _item("6", "30.00", "0.00", "30.00", fee_date=fd),         # 小换药
        _item("7", "46.00", "46.00", "0.00", fee_date=fd),         # 复方丹参滴丸
        _item("8", "1350.00", "1215.00", "135.00", "135.00", fd),  # 注射用培美曲塞二钠
        _item("9", "130.00", "117.00", "13.00", "13.00", fd),      # 清脑复神液
        _item("10", "230.00", "230.00", "0.00", fee_date=fd),      # 他克莫司胶囊
        _item("11", "100.00", "100.00", "0.00", fee_date=fd),      # 医事服务费
        _item("12", "26.00", "26.00", "0.00", fee_date=fd),        # Ⅱ级护理
        _item("13", "60.00", "50.00", "10.00", "10.00", fd),       # 三人间床位费
        _item("14", "60.00", "0.00", "60.00", fee_date=fd),        # 病房空调费
        _item("15", "28.00", "28.00", "0.00", fee_date=fd),        # 呼吸机吸氧
        _item("16", "68.00", "68.00", "0.00", fee_date=fd),        # 静脉输血
        _item("17", "1.33", "1.33", "0.00", fee_date=fd),          # 真空采血管
        _item("18", "566.33", "566.33", "0.00", fee_date=fd),      # 人工晶体
    )
    observed = SpecialObservedAmounts(
        zje=Decimal("3055.66"), ybn=Decimal("2551.26"), ybw=Decimal("504.40"),
        ybnqfje=Decimal("0.00"), tczhf=Decimal("2321.65"), tczif=Decimal("229.61"),
        degwyzhf=Decimal("0.00"), degwyzif=Decimal("0.00"),
        bczhf=Decimal("114.81"),  # ESP-RSUP-001 remark：djh=705 实测 114.805→114.81
        jczhf=Decimal("0.00"), gfylbchbx=Decimal("0.00"),
        grziftw=Decimal("164.40"),
    )
    cycle = SpecialCycleContext(
        deductible_standard=Decimal("1300"), prior_cycle_deductible_paid=Decimal("1300"),
        evidence_status="confirmed",
        evidence_note="手算样例：年度内门特起付已承担，本次 F=0",
    )
    return _snapshot(djh="705", cblb="21", settle_date=D(2024, 9, 25),
                     items=items, observed=observed, cycle=cycle,
                     retirement_category="normal")


def test_golden_djh705_retired_mixed_18_lines():
    result = decompose_employee_outpatient_special(_snapshot_djh705())
    fields = _fields(result)
    # 逐行合计与账面一致（含亚分精度行 1.33/566.33）
    assert fields["ZJE"].check_status == "matched"      # 3055.66
    assert fields["YBN"].check_status == "matched"      # 2551.26
    assert fields["YBW"].check_status == "matched"      # 504.40
    assert fields["GRZIFTW"].check_status == "matched"  # 164.40
    # 统筹 = 2551.26×91% = 2321.6466 → HALF_UP 2321.65
    assert fields["TCZHF"].calculated_amount == "2321.65"
    assert fields["TCZHF"].check_status == "matched"
    assert fields["TCZIF"].calculated_amount == "229.61"
    assert fields["TCZIF"].check_status == "matched"
    # 退休补助 = 229.61×50% = 114.805 → HALF_UP 114.81
    assert fields["BCZHF"].calculated_amount == "114.81"
    assert fields["BCZHF"].check_status == "matched"


# ── fail-closed 行为 ──────────────────────────────────────────


def test_unknown_cycle_context_not_verifiable():
    """周期上下文 unknown：起付及统筹/大额字段不可独立计算，不回填账面值。"""
    snap = _snapshot(
        djh="700", cblb="21", settle_date=D(2024, 9, 26),
        items=(_item("1", "3936.00", "3936.00", "0.00"),),
        observed=SpecialObservedAmounts(
            zje=Decimal("3936.00"), ybn=Decimal("3936.00"), ybw=Decimal("0.00"),
            ybnqfje=Decimal("0.00"), tczhf=Decimal("3581.76"), tczif=Decimal("354.24"),
        ),
        cycle=SpecialCycleContext(evidence_status="unknown"),
        retirement_category="normal",
    )
    result = decompose_employee_outpatient_special(snap)
    fields = _fields(result)
    assert fields["YBNQFJE"].check_status == "not_verifiable"
    assert fields["YBNQFJE"].calculated_amount is None
    assert fields["TCZHF"].check_status == "not_verifiable"
    assert any(u.code == "MISSING_CYCLE_CONTEXT" for u in result.uncertainties)


def test_observed_deductible_as_input_marked_reconciliation_only():
    """评估口径开关：账面起付作条件输入，显式标注 OBSERVED_DEDUCTIBLE_AS_INPUT。"""
    snap = _snapshot(
        djh="604", cblb="11", settle_date=D(2024, 9, 18),
        items=(_item("1", "3200.00", "2880.00", "320.00", advance="320.00"),
               _item("2", "2230.00", "2007.00", "223.00", advance="223.00")),
        observed=SpecialObservedAmounts(
            zje=Decimal("5430.00"), ybn=Decimal("4887.00"), ybw=Decimal("543.00"),
            ybnqfje=Decimal("650.00"), tczhf=Decimal("3601.45"), tczif=Decimal("635.55"),
        ),
        cycle=SpecialCycleContext(evidence_status="unknown"),
        allow_observed_deductible=True,
    )
    result = decompose_employee_outpatient_special(snap)
    fields = _fields(result)
    # 账面起付 650 作条件输入继续计算：统筹/自付可核对（原样透传账面精度）
    assert fields["YBNQFJE"].calculated_amount == "650.00"
    assert fields["TCZHF"].calculated_amount == "3601.45"
    assert fields["TCZHF"].check_status == "matched"
    # 勾稽级标注：不升级为因果级解释
    assert any(u.code == "OBSERVED_DEDUCTIBLE_AS_INPUT" for u in result.uncertainties)
    assert "u.deductible.observed_book" in fields["TCZHF"].uncertainty_refs


def test_unsupported_profile_unavailable():
    """非职工×门特组合：unavailable，不套用门特公式。"""
    snap = _snapshot(
        djh="604", cblb="11", settle_date=D(2024, 9, 18),
        items=(_item("1", "100.00", "100.00", "0.00"),),
        observed=SpecialObservedAmounts(zje=Decimal("100.00")),
        cycle=SpecialCycleContext(evidence_status="unknown"),
        insurance_type="resident",
    )
    result = decompose_employee_outpatient_special(snap)
    assert result.execution_status == "unavailable"
    assert any(u.code == "UNSUPPORTED_PROFILE" for u in result.uncertainties)


def test_negative_amount_unavailable():
    """负金额明细：不取绝对值套正向公式，直接 unavailable。"""
    snap = _snapshot(
        djh="604", cblb="11", settle_date=D(2024, 9, 18),
        items=(_item("1", "-100.00", "-100.00", "0.00"),),
        observed=SpecialObservedAmounts(zje=Decimal("-100.00")),
        cycle=SpecialCycleContext(evidence_status="unknown"),
    )
    result = decompose_employee_outpatient_special(snap)
    assert result.execution_status == "unavailable"
    assert any(u.code == "UNSUPPORTED_REVERSAL_OR_NEGATIVE" for u in result.uncertainties)
