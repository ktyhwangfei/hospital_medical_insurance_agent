"""门诊大额支付单元测试（设计 §7.4 / §14 待遇矩阵）。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    BranchOutcome,
    InstitutionKind,
    PersonKind,
    RoundingMode,
)
from src.runtime.policy_qa.fee_decomposition.big_pay import decompose_big_pay, full_age_at

MODE = RoundingMode.HALF_UP
D = date


def _run(
    base="1000.00",
    person=PersonKind.EMPLOYED,
    birth=None,
    inst=InstitutionKind.OTHER,
    on=D(2024, 6, 1),
    prior_fund=Decimal("0.00"),
    confirmed=True,
):
    return decompose_big_pay(
        Decimal(base) if base is not None else None,
        person, birth, inst, on,
        prior_fund, confirmed, MODE,
    )


# ── 基础比例档 ──


def test_employed_community_90pct():
    res = _run(inst=InstitutionKind.COMMUNITY)
    assert res.big_pay == Decimal("900.00") and res.big_self_pay == Decimal("100.00")


def test_employed_other_70pct():
    res = _run()
    assert res.big_pay == Decimal("700.00") and res.big_self_pay == Decimal("300.00")


def test_retired_lt70_community_80pct():
    res = _run(person=PersonKind.RETIRED, birth=D(1960, 1, 1), inst=InstitutionKind.COMMUNITY)
    assert res.big_pay == Decimal("800.00")


def test_retired_lt70_other_70pct():
    res = _run(person=PersonKind.RETIRED, birth=D(1960, 1, 1))
    assert res.big_pay == Decimal("700.00")


def test_retired_ge70_80pct_regardless_institution():
    # ≥70 周岁单一档 80%，机构维度不区分（机构未知也可确定）
    res = _run(person=PersonKind.RETIRED, birth=D(1950, 1, 1), inst=InstitutionKind.UNKNOWN)
    assert res.big_pay == Decimal("800.00")


def test_birthday_boundary_full_age():
    # 70 周岁生日当日已满 70 → 80%
    res = _run(person=PersonKind.RETIRED, birth=D(1954, 6, 1), on=D(2024, 6, 1))
    assert res.big_pay == Decimal("800.00")
    # 生日前一天 69 周岁 → <70 档（其他医院 70%）
    res2 = _run(person=PersonKind.RETIRED, birth=D(1954, 6, 1), on=D(2024, 5, 31))
    assert res2.big_pay == Decimal("700.00")
    assert full_age_at(D(1954, 6, 1), D(2024, 6, 1)) == 70
    assert full_age_at(D(1954, 6, 1), D(2024, 5, 31)) == 69


def test_unknown_person_kind_not_defaulted():
    res = _run(person=PersonKind.UNKNOWN)
    assert res.big_pay is None
    assert any(b.reason_code == "PERSON_KIND_UNKNOWN" for b in res.branches)


def test_unknown_institution_unknown_when_discriminating():
    res = _run(inst=InstitutionKind.UNKNOWN)
    assert res.big_pay is None
    assert any(b.reason_code == "INSTITUTION_KIND_UNKNOWN" for b in res.branches)


def test_missing_birth_date_retired_unknown():
    res = _run(person=PersonKind.RETIRED, birth=None)
    assert res.big_pay is None
    assert any(b.reason_code == "BIRTH_DATE_MISSING" for b in res.branches)
    # 在职不需要年龄：年龄档分支 not_evaluated
    res2 = _run()
    age_branch = [b for b in res2.branches if b.step_id == "big_pay.age_band"][0]
    assert age_branch.outcome == BranchOutcome.NOT_EVALUATED


# ── 封顶与分段（基金支付累计口径） ──


def test_fund_cumulative_missing_unknown():
    res = _run(prior_fund=None)
    assert res.big_pay is None
    assert any(u.code == "FUND_CUMULATIVE_MISSING" for u in res.uncertainties)


def test_fund_cumulative_unconfirmed_caliber_unknown():
    res = _run(confirmed=False)
    assert res.big_pay is None
    assert any(b.reason_code == "FUND_CUMULATIVE_CALIBER_UNCONFIRMED" for b in res.branches)


def test_2022_cap_limits_fund_payment():
    # 2022 年：基金支付累计 19900，B=1000×70%=700，但封顶 20000 → 只付 100
    res = _run(on=D(2022, 6, 1), prior_fund=Decimal("19900.00"))
    assert res.big_pay == Decimal("100.00")
    assert res.big_self_pay == Decimal("900.00")
    assert any(u.code == "BEYOND_CAP_FIELD_ATTRIBUTION_UNCONFIRMED" for u in res.uncertainties)


def test_2023_no_cap_below_threshold():
    res = _run(on=D(2024, 6, 1), prior_fund=Decimal("10000.00"))
    assert res.big_pay == Decimal("700.00")  # 无封顶，全额按 70%
    cap_branch = [b for b in res.branches if b.step_id == "big_pay.cap_regime"][0]
    assert cap_branch.outcome == BranchOutcome.FALSE
    assert cap_branch.reason_code == "CAP_ABOLISHED_FROM_2023"


def test_2023_excess_segment_60pct():
    # 基金累计 19900：边界换算 B1=(20000-19900)/0.7≈142.86，余下按 60%
    res = _run(on=D(2024, 6, 1), prior_fund=Decimal("19900.00"))
    segs = {s.name: s for s in res.segments}
    assert "excess_20k" in segs
    # pay1=round(142.857…×0.7)=100.00；pay2=round(857.142…×0.6)=514.29
    assert segs["base"].pay == Decimal("100.00")
    assert segs["excess_20k"].pay == Decimal("514.29")
    assert res.big_pay == Decimal("614.29")
    assert segs["excess_20k"].rule_id == "EOP-RATE-301"


def test_2023_all_beyond_threshold_60pct():
    res = _run(on=D(2024, 6, 1), prior_fund=Decimal("25000.00"))
    assert res.big_pay == Decimal("600.00")
    assert [s.name for s in res.segments] == ["base", "excess_20k"]
    assert res.segments[0].base_amount == 0


def test_base_missing_blocked():
    res = decompose_big_pay(None, PersonKind.EMPLOYED, None, InstitutionKind.OTHER,
                            D(2024, 6, 1), Decimal("0"), True, MODE)
    assert res.branches[0].outcome == BranchOutcome.BLOCKED
