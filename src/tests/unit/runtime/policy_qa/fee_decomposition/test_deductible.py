"""起付线分解单元测试（设计 §7.3 / §14 起付矩阵）。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.domain.insurance.fee_decomposition import BranchOutcome, PersonKind
from src.runtime.policy_qa.fee_decomposition.deductible import decompose_deductible

D = date


def _run(e, a, person=PersonKind.EMPLOYED, on=D(2024, 5, 1), confirmed=True):
    return decompose_deductible(e, a, confirmed, person, on)


def test_below_deductible_all_self_paid():
    # 起付前：A=1000，E=500，D=1800 → F=500，B=0
    res = _run(Decimal("500.00"), Decimal("1000.00"))
    assert res.deductible_paid == Decimal("500.00")
    assert res.copay_base == Decimal("0.00")


def test_crossing_deductible():
    # 跨线：A=1700，E=500 → F=100，B=400
    res = _run(Decimal("500.00"), Decimal("1700.00"))
    assert res.deductible_paid == Decimal("100.00")
    assert res.copay_base == Decimal("400.00")


def test_above_deductible():
    # 线上：A=2000 ≥ D → F=0
    res = _run(Decimal("500.00"), Decimal("2000.00"))
    assert res.deductible_paid == Decimal("0")
    assert res.copay_base == Decimal("500.00")


def test_retired_uses_1300_standard():
    res = _run(Decimal("500.00"), Decimal("1200.00"), person=PersonKind.RETIRED)
    assert res.deductible_paid == Decimal("100.00")


def test_historical_version_2005_employed_2000():
    res = _run(Decimal("500.00"), Decimal("0.00"), on=D(2005, 6, 1))
    assert res.deductible_paid == Decimal("500.00")  # D=2000（EOP-DED-001）
    assert any(b.rule_refs for b in res.branches)


def test_prior_accumulation_unconfirmed_caliber_stays_unknown():
    # TB_FeeIn 是否交易前累计不明 → 保留轨迹不硬算
    res = _run(Decimal("500.00"), Decimal("1000.00"), confirmed=False)
    assert res.deductible_paid is None and res.copay_base is None
    b = [b for b in res.branches if b.step_id == "deductible.prior_accumulation"][0]
    assert b.outcome == BranchOutcome.UNKNOWN
    assert b.reason_code == "PRIOR_ACCUMULATION_CALIBER_UNCONFIRMED"


def test_prior_accumulation_missing_unknown():
    res = _run(Decimal("500.00"), None)
    assert res.deductible_paid is None
    assert any(u.code == "PRIOR_ACCUMULATION_MISSING" for u in res.uncertainties)


def test_unknown_person_kind_unknown():
    res = _run(Decimal("500.00"), Decimal("0.00"), person=PersonKind.UNKNOWN)
    assert res.deductible_paid is None
    assert any(b.reason_code == "PERSON_KIND_UNKNOWN" for b in res.branches)


def test_missing_base_blocked_not_not_applicable():
    res = decompose_deductible(None, Decimal("0.00"), True, PersonKind.EMPLOYED, D(2024, 5, 1))
    b = res.branches[0]
    assert b.outcome == BranchOutcome.BLOCKED and b.reason_code == "UPSTREAM_BASE_MISSING"
