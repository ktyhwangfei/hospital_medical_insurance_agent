"""退休补充、军残、公疗补助单元测试（设计 §7.5 / §14 补充待遇矩阵）。

§7.5.5 四个算术示例逐金额断言（S=100）。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    BranchOutcome,
    PersonKind,
    RoundingMode,
)
from src.runtime.policy_qa.fee_decomposition.supplements import (
    RURAL_EXCLUSION_REASON,
    military_supplement,
    public_medical_supplement,
    retire_supplement,
)

MODE = RoundingMode.HALF_UP
D = date
S100 = Decimal("100.00")


def _rsup(
    s=S100, person=PersonKind.RETIRED, category="normal",
    enroll=D(2006, 4, 1), on=D(2024, 5, 1),
):
    return retire_supplement(s, person, category, enroll, on, MODE)


def _dvet(
    s=S100, r_amount=None, r_outcome=BranchOutcome.NOT_APPLICABLE,
    person=PersonKind.EMPLOYED, veteran=True, grade="5-6",
    eligible_from=D(2006, 10, 1), eligible_to=None,
    rural=False, pmed=False, fee_dates=(D(2024, 5, 1),),
):
    return military_supplement(
        s, r_amount, r_outcome, person, veteran, grade,
        eligible_from, eligible_to, rural, pmed, fee_dates, MODE,
    )


# ── §7.5.5 补助链算术示例 ──


def test_chain_retired_normal_grade56():
    r = _rsup()
    assert r.amount == Decimal("50.00")
    j = _dvet(r_amount=r.amount, r_outcome=r.outcome, person=PersonKind.RETIRED)
    assert j.amount == Decimal("25.00")
    assert S100 - r.amount - j.amount == Decimal("25.00")


def test_chain_retired_prepaid_grade56():
    r = _rsup(category="prepaid")
    assert r.amount == Decimal("60.00")
    j = _dvet(r_amount=r.amount, r_outcome=r.outcome, person=PersonKind.RETIRED)
    assert j.amount == Decimal("20.00")
    assert S100 - r.amount - j.amount == Decimal("20.00")


def test_chain_retired_normal_grade14():
    r = _rsup()
    assert r.amount == Decimal("50.00")
    j = _dvet(r_amount=r.amount, r_outcome=r.outcome, person=PersonKind.RETIRED, grade="1-4")
    assert j.amount == Decimal("50.00")
    assert S100 - r.amount - j.amount == Decimal("0.00")


def test_chain_employed_grade56():
    r = _rsup(person=PersonKind.EMPLOYED)
    assert r.outcome == BranchOutcome.NOT_APPLICABLE and r.amount == Decimal("0")
    j = _dvet(person=PersonKind.EMPLOYED)
    assert j.amount == Decimal("70.00")
    assert S100 - r.amount - j.amount == Decimal("30.00")


# ── 退休补充保险资格与类别 ──


def test_retire_category_unknown_not_default_50pct():
    r = _rsup(category=None)
    assert r.amount is None and r.outcome == BranchOutcome.UNKNOWN
    assert any(b.reason_code == "RETIREMENT_CATEGORY_UNKNOWN" for b in r.branches)


def test_retire_enroll_date_boundary():
    # 起始日前 → 不适用；起始日当日按「起始日纳入」
    before = _rsup(enroll=D(2024, 6, 1), on=D(2024, 5, 31))
    assert before.outcome == BranchOutcome.NOT_APPLICABLE and before.amount == Decimal("0")
    on_day = _rsup(enroll=D(2024, 6, 1), on=D(2024, 6, 1))
    assert on_day.outcome == BranchOutcome.TRUE and on_day.amount == Decimal("50.00")


def test_retire_enroll_date_missing_unknown():
    r = _rsup(enroll=None)
    assert r.outcome == BranchOutcome.UNKNOWN
    assert any(u.code == "SUPPLEMENT_ENROLL_DATE_MISSING" for u in r.uncertainties)


def test_retire_base_missing_blocked():
    r = _rsup(s=None)
    assert r.outcome == BranchOutcome.BLOCKED


# ── 军残资格与依赖 ──


def test_military_retired_r_unknown_blocked_not_zero():
    # R 未知不得用零代替
    j = _dvet(r_amount=None, r_outcome=BranchOutcome.UNKNOWN, person=PersonKind.RETIRED)
    assert j.outcome == BranchOutcome.BLOCKED
    assert any(b.reason_code == "RETIRE_SUPPLEMENT_UNKNOWN" for b in j.branches)


def test_military_rural_public_medical_exclusion():
    j = _dvet(rural=True, pmed=True)
    assert j.outcome == BranchOutcome.NOT_APPLICABLE
    assert j.reason_code == RURAL_EXCLUSION_REASON
    assert j.amount == Decimal("0")


def test_military_rural_status_unknown_not_defaulted():
    j = _dvet(rural=None, pmed=True)
    assert j.outcome == BranchOutcome.UNKNOWN
    assert j.reason_code == "RURAL_PMED_STATUS_UNKNOWN"


def test_military_veteran_status_unknown():
    j = _dvet(veteran=None)
    assert j.outcome == BranchOutcome.UNKNOWN
    assert j.reason_code == "DISABLED_VETERAN_STATUS_UNKNOWN"


def test_military_not_veteran_not_applicable():
    j = _dvet(veteran=False)
    assert j.outcome == BranchOutcome.NOT_APPLICABLE and j.amount == Decimal("0")


def test_military_eligibility_by_fee_date():
    # 全部明细在资格期前 → 不适用
    before = _dvet(eligible_from=D(2024, 6, 1), fee_dates=(D(2024, 5, 1),))
    assert before.outcome == BranchOutcome.NOT_APPLICABLE
    # 跨资格生效日 → blocked，不按比例摊分
    mixed = _dvet(eligible_from=D(2024, 4, 15), fee_dates=(D(2024, 4, 1), D(2024, 5, 1)))
    assert mixed.outcome == BranchOutcome.BLOCKED
    assert mixed.reason_code == "CROSS_DATE_ALLOCATION_UNCONFIRMED"


def test_military_eligibility_period_unknown():
    j = _dvet(eligible_from=None, eligible_to=None)
    assert j.outcome == BranchOutcome.UNKNOWN
    assert j.reason_code == "MILITARY_ELIGIBILITY_PERIOD_UNKNOWN"


# ── 公疗（§7.5.4） ──


def _pmed(
    a_in=Decimal("1200.00"), e_in=Decimal("300.00"), person=PersonKind.RETIRED,
    rural=False, eligible=True, designated=True, prior_on_g=Decimal("150.00"),
    on=D(2024, 5, 1),
):
    return public_medical_supplement(
        a_in, e_in, person, rural, eligible, designated, prior_on_g, on, MODE,
    )


def test_pmed_below_threshold_zero():
    # A_in=1000，E_in=200 → G=0（累计未超 1300）
    o = _pmed(a_in=Decimal("1000.00"), e_in=Decimal("200.00"))
    assert o.outcome == BranchOutcome.TRUE and o.amount == Decimal("0")
    assert o.reason_code == "BELOW_PMED_THRESHOLD"


def test_pmed_crossing_threshold_retired_95pct():
    # 设计 §7.5.4 算术例：A_in=1200，E_in=300 → G=200；目标 95% → 190；已有 150 → O=40
    o = _pmed()
    assert o.outcome == BranchOutcome.TRUE and o.amount == Decimal("40.00")
    g_branch = [b for b in o.branches if b.step_id == "pmed.threshold_segment"][0]
    assert g_branch.condition.actual_value == "200.00"


def test_pmed_employed_90pct():
    o = _pmed(person=PersonKind.EMPLOYED, prior_on_g=Decimal("100.00"))
    assert o.amount == Decimal("80.00")  # 200×90% - 100


def test_pmed_rural_veteran_100pct():
    o = _pmed(rural=True, prior_on_g=Decimal("120.00"))
    assert o.amount == Decimal("80.00")  # 200×100% - 120


def test_pmed_prior_exceeds_target_conflict_no_negative():
    # 已有支付 195 > 目标 190 → O=0，保留冲突诊断，不输出负补助
    o = _pmed(prior_on_g=Decimal("195.00"))
    assert o.amount == Decimal("0")
    assert any(u.code == "PMED_PRIOR_EXCEEDS_TARGET" for u in o.uncertainties)
    conflict = [b for b in o.branches if b.step_id == "pmed.conflict"][0]
    assert conflict.outcome == BranchOutcome.FALSE


def test_pmed_eligibility_unknown():
    o = _pmed(eligible=None)
    assert o.outcome == BranchOutcome.UNKNOWN
    o2 = _pmed(designated=None)
    assert o2.outcome == BranchOutcome.UNKNOWN
    assert o2.reason_code == "DESIGNATED_HOSPITAL_UNKNOWN"
    o3 = _pmed(designated=False)
    assert o3.outcome == BranchOutcome.NOT_APPLICABLE and o3.amount == Decimal("0")


def test_pmed_accumulation_missing_unknown():
    o = _pmed(a_in=None)
    assert o.outcome == BranchOutcome.UNKNOWN
    assert o.reason_code == "PMED_ACCUMULATION_MISSING"


def test_pmed_prior_fund_allocation_unknown():
    o = _pmed(prior_on_g=None)
    assert o.outcome == BranchOutcome.UNKNOWN
    assert o.reason_code == "PMED_PRIOR_FUND_ALLOCATION_UNKNOWN"
