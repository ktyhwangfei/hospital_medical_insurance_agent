"""城乡居民门特待遇参数表（Issue #81 RSP-* 系列）单元测试。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.domain.insurance.fee_decomposition import BranchOutcome
from src.runtime.policy_qa.fee_decomposition.params_resident_outpatient_special import (
    PARAMS,
    STUDENT_CHILD_PERSON_TYPE_CODES,
    get_param,
    institution_level_from_h_level,
    is_student_child,
    select_resident_special_big_pay_rate_param,
    select_resident_special_cap_param,
    select_resident_special_deductible_param,
)


def test_param_ids_unique_and_prefixed():
    ids = [p.rule_id for p in PARAMS]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("RSP-") for i in ids)


def test_student_child_set():
    assert "14" in STUDENT_CHILD_PERSON_TYPE_CODES
    assert "17" not in STUDENT_CHILD_PERSON_TYPE_CODES  # 城镇老年人不在学生儿童集合
    assert "70" not in STUDENT_CHILD_PERSON_TYPE_CODES  # 无业居民不在集合
    assert is_student_child("15") and not is_student_child("17") and not is_student_child(None)


def test_deductible_elderly_first_cycle_tier3():
    # 老年/无业 + 三级 + 第一周期 → 1300（实证：688/690/718 bqqfje=1300）
    sel = select_resident_special_deductible_param("70", "3", "first", date(2024, 9, 25))
    assert sel.outcome == BranchOutcome.TRUE
    assert sel.param.rule_id == "RSP-DED-001" and sel.param.value == 1300


def test_deductible_elderly_subsequent_cycle_tier3():
    # 老年/无业 + 三级 + 第二及以后 → 650（减半）
    sel = select_resident_special_deductible_param("17", "3", "subsequent", date(2024, 9, 25))
    assert sel.outcome == BranchOutcome.TRUE
    assert sel.param.rule_id == "RSP-DED-002" and sel.param.value == 650


def test_deductible_student_child_tier3():
    # 学生儿童 + 三级 → 650（每次均收不再减半，周期位置不影响）
    sel = select_resident_special_deductible_param("15", "3", "subsequent", date(2024, 9, 25))
    assert sel.outcome == BranchOutcome.TRUE
    assert sel.param.rule_id == "RSP-DED-003" and sel.param.value == 650


def test_deductible_tier2_and_tier1():
    assert select_resident_special_deductible_param(
        "70", "2", "first", date(2024, 9, 25)).param.value == 800
    assert select_resident_special_deductible_param(
        "70", "1", "first", date(2024, 9, 25)).param.value == 300
    assert select_resident_special_deductible_param(
        "15", "2", "first", date(2024, 9, 25)).param.value == 400
    assert select_resident_special_deductible_param(
        "15", "1", "first", date(2024, 9, 25)).param.value == 150


def test_deductible_unknown_inputs_blocked():
    assert select_resident_special_deductible_param(
        None, "3", "first", date(2024, 9, 25)).outcome == BranchOutcome.UNKNOWN
    assert select_resident_special_deductible_param(
        "70", None, "first", date(2024, 9, 25)).outcome == BranchOutcome.UNKNOWN


def test_big_pay_rate_by_institution_level():
    sel3 = select_resident_special_big_pay_rate_param("3", date(2024, 9, 25))
    assert sel3.outcome == BranchOutcome.TRUE and sel3.param.ratio == Decimal("0.75")
    sel2 = select_resident_special_big_pay_rate_param("2", date(2024, 9, 25))
    assert sel2.param.ratio == Decimal("0.78")
    sel1 = select_resident_special_big_pay_rate_param("1", date(2024, 9, 25))
    assert sel1.param.ratio == Decimal("0.80")
    assert select_resident_special_big_pay_rate_param(
        None, date(2024, 9, 25)).outcome == BranchOutcome.UNKNOWN


def test_cap_version_by_date():
    assert select_resident_special_cap_param(date(2018, 6, 1)).param.value == 200000
    assert select_resident_special_cap_param(date(2024, 9, 25)).param.value == 250000


def test_institution_level_mapping():
    assert institution_level_from_h_level("02") == "3"  # 三级甲等（本院）
    assert institution_level_from_h_level("07") == "2"
    assert institution_level_from_h_level("10") == "1"
    assert institution_level_from_h_level("14") == "1"  # 未评级
    assert institution_level_from_h_level(None) is None
    assert institution_level_from_h_level("x") is None


def test_pending_confirmation_rounding_param():
    assert get_param("RSP-RND-001").confirmation_status == "待确认"
