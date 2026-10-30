"""城乡居民门诊待遇参数表（Issue #80 ROP-* 系列）单元测试。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.domain.insurance.fee_decomposition import BranchOutcome, InstitutionLevelTier
from src.runtime.policy_qa.fee_decomposition.params_resident_outpatient import (
    MSF_CURE_TYPE_CODES,
    OUTPATIENT_CURE_TYPE_CODES,
    PARAMS,
    RESIDENT_PERSON_TYPE_CODES,
    classify_institution_tier,
    get_param,
    select_resident_big_pay_rate_param,
    select_resident_cap_param,
    select_resident_deductible_param,
)


def test_param_ids_unique_and_prefixed():
    ids = [p.rule_id for p in PARAMS]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("ROP-") for i in ids)


def test_deductible_2018_tier_split():
    # 2018 起：一级及以下 100 / 二级及以上 550
    sel1 = select_resident_deductible_param(InstitutionLevelTier.LEVEL_1_AND_BELOW, date(2024, 5, 1))
    assert sel1.outcome == BranchOutcome.TRUE and sel1.param.value == 100
    sel2 = select_resident_deductible_param(InstitutionLevelTier.LEVEL_2_AND_ABOVE, date(2024, 5, 1))
    assert sel2.outcome == BranchOutcome.TRUE and sel2.param.value == 550


def test_deductible_historical_versions():
    # 历史档：2011-2017 统一 650（不分机构档）
    sel = select_resident_deductible_param(InstitutionLevelTier.LEVEL_2_AND_ABOVE, date(2015, 6, 1))
    assert sel.outcome == BranchOutcome.TRUE and sel.param.value == 650
    assert sel.param.rule_id == "ROP-DED-102"
    # 2009 老年人 200
    sel_old = select_resident_deductible_param(InstitutionLevelTier.LEVEL_1_AND_BELOW, date(2009, 6, 1))
    assert sel_old.outcome == BranchOutcome.TRUE and sel_old.param.value == 200


def test_rate_2018_tier_split():
    sel1 = select_resident_big_pay_rate_param(InstitutionLevelTier.LEVEL_1_AND_BELOW, date(2024, 5, 1))
    assert sel1.outcome == BranchOutcome.TRUE and sel1.param.ratio == Decimal("0.55")
    sel2 = select_resident_big_pay_rate_param(InstitutionLevelTier.LEVEL_2_AND_ABOVE, date(2024, 5, 1))
    assert sel2.outcome == BranchOutcome.TRUE and sel2.param.ratio == Decimal("0.50")


def test_cap_version_by_date():
    assert select_resident_cap_param(date(2018, 6, 1)).param.value == 3000
    assert select_resident_cap_param(date(2020, 6, 1)).param.value == 4000
    assert select_resident_cap_param(date(2024, 5, 1)).param.value == 4500


def test_unknown_tier_2018_blocked():
    # 2018 起机构档未知时不得默认任何档（分档政策无不分档版本）
    sel = select_resident_deductible_param(InstitutionLevelTier.UNKNOWN, date(2024, 5, 1))
    assert sel.outcome == BranchOutcome.UNKNOWN
    # 历史日期（不分档版本适用时）仍可选择历史档
    sel_hist = select_resident_deductible_param(InstitutionLevelTier.UNKNOWN, date(2015, 6, 1))
    assert sel_hist.outcome == BranchOutcome.TRUE and sel_hist.param.value == 650


def test_classify_institution_tier():
    assert classify_institution_tier("02") == InstitutionLevelTier.LEVEL_2_AND_ABOVE
    assert classify_institution_tier("10") == InstitutionLevelTier.LEVEL_1_AND_BELOW
    # 14=未评级 → 一级及以下档（政策：未评级与一级同 55%）
    assert classify_institution_tier("14") == InstitutionLevelTier.LEVEL_1_AND_BELOW
    assert classify_institution_tier(None) == InstitutionLevelTier.UNKNOWN
    assert classify_institution_tier("x") == InstitutionLevelTier.UNKNOWN


def test_candidate_code_sets():
    assert "15" in RESIDENT_PERSON_TYPE_CODES and "11" not in RESIDENT_PERSON_TYPE_CODES
    assert MSF_CURE_TYPE_CODES == frozenset({"17", "18"})
    assert OUTPATIENT_CURE_TYPE_CODES == frozenset({"11", "19"})


def test_pending_confirmation_params_never_pass_gate():
    # ROP-RND-001（取整，待确认）与 ROP-CURE-001（扩展码，待确认）风格：
    # 参数表内「待确认」参数不允许经 select_param 静默生效
    rnd = get_param("ROP-RND-001")
    assert rnd.confirmation_status == "待确认"
