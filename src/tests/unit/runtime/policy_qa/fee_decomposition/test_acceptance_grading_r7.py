"""R7：验收判定必须能否定错误实现（2026-10-27 任务书 D1–D8）。

覆盖两类假通过：
- 旧判定用「第二个数字 + 计算/支付等词」就判原因已解释（年份、其他字段金额也能过）；
- 真实验收构造 requirement 时不传构成/来源要求，错误等式仍判通过。

判定分两个轴：
- content_status：reason_explained / book_fact / not_applicable / missing_evidence；
- delivered：是否如实交付该目标（漏答、空正文、泛泛"资料不足"都不算交付；
  诚实点名的缺证算交付，但状态仍是 missing_evidence）。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.tests.unit.runtime.policy_qa.fee_decomposition.test_acceptance_grading import (
    MISSING_EVIDENCE,
    REASON_EXPLAINED,
    TargetRequirement,
    acceptance_summary,
    assess_target,
    undelivered,
)

BIG_PAY = TargetRequirement(
    key="resident-outpatient-0408.big_pay",
    label="大额支付",
    amount="1597.50",
    kind="explainable",
    required_values=("3195", "2195.50"),
    required_tokens=("×", "取整"),
    forbidden_tokens=("×50%－2304.50", "×50%-2304.50", "÷50%"),
    required_sources=("居民门诊待遇参数表",),
)

GOOD_BIG_PAY = (
    "- 大额支付 1597.50 元；构成：较小值（取整（基数 3195.00 元×比例 50%），"
    "封顶余额 2195.50 元）＝1597.50 元；来源：居民门诊待遇参数表。")


def test_requirement_construction_errors_are_explicit():
    """可解释目标未登记必要构成 → 配置本身报错，不能默认空要求通过。"""
    with pytest.raises(ValueError):
        TargetRequirement.check({"kind": "explainable", "required_values": (),
                                 "required_tokens": (), "required_sources": ()})
    TargetRequirement.check({"kind": "observed_only", "required_values": (),
                             "required_tokens": (), "required_sources": ()})


def test_d1_no_computation_is_not_reason_explained():
    answer = "大额支付 1597.50 元；计算过程尚未提供，来源 2024 年。"
    assessment = assess_target(answer, BIG_PAY)
    assert assessment.status == MISSING_EVIDENCE
    assert assessment.delivered is False


def test_d2_wrong_equation_fails_even_with_numbers_and_source():
    answer = ("大额支付 1597.50 元；构成：3195×50%－2304.50＝1597.50；"
              "来源：居民门诊待遇参数表。")
    assert assess_target(answer, BIG_PAY).status == MISSING_EVIDENCE
    assert assess_target(answer, BIG_PAY).delivered is False


def test_d3_other_amount_cannot_stand_in_for_composition():
    answer = "大额支付 1597.50 元；暂无计算，但其他金额 100.00 元。"
    assert assess_target(answer, BIG_PAY).status == MISSING_EVIDENCE


def test_d4_wrong_field_or_other_line_source_fails():
    wrong_field = "个人支付总金额 1597.50 元；构成：3195×50% 取整；来源：居民门诊待遇参数表。"
    assert assess_target(wrong_field, BIG_PAY).status == MISSING_EVIDENCE

    split = "\n".join([
        "大额支付 1597.50 元；构成：较小值（取整（3195×50%），封顶余额 2195.50 元）＝1597.50 元。",
        "费用总金额 3435.00 元；来源：居民门诊待遇参数表。",
    ])
    assert assess_target(split, BIG_PAY).status == MISSING_EVIDENCE
    # 本次回答的 citations 才算来源，且不能借用另一轮
    assert assess_target(split, BIG_PAY,
                         citations=("居民门诊待遇参数表",)).status == REASON_EXPLAINED


def test_d5_zero_branch_and_zero_unknown_status():
    zero_branch = "- 大额自付 0.00 元；构成：0.00＋0.00＝0.00 元；来源：本单结算记录。"
    requirement = TargetRequirement(
        "employee-special-567.big_self_pay", "大额自付", "0.00", "explainable",
        required_values=("0.00",), required_tokens=("＋",),
        required_sources=("本单结算记录",))
    assert assess_target(zero_branch, requirement).status == REASON_EXPLAINED

    unknown = "- 残疾军人补助 0.00 元；资格资料不足，不能仅凭零金额判断没有资格。"
    missing = TargetRequirement(
        "employee-outpatient-000008.military_pay", "残疾军人补助", "0.00", "missing",
        gap_markers=("资格资料不足",))
    assessment = assess_target(unknown, missing)
    assert assessment.status == MISSING_EVIDENCE
    assert assessment.delivered is True


def test_d6_generic_gap_is_not_delivery():
    requirement = TargetRequirement(
        "employee-outpatient-000008.military_pay", "残疾军人补助", "0.00", "missing",
        gap_markers=("资格资料不足", "DISABLED_VETERAN_STATUS_UNKNOWN"))
    assert assess_target("- 残疾军人补助 0.00 元；资料不足。",
                         requirement).delivered is False
    assert assess_target("", requirement).delivered is False
    assert undelivered(
        "- 残疾军人补助 0.00 元；资格资料不足（DISABLED_VETERAN_STATUS_UNKNOWN）。",
        [requirement]) == []


def test_d7_operator_line_and_source_mutations_fail():
    assert assess_target(GOOD_BIG_PAY, BIG_PAY).status == REASON_EXPLAINED
    # 只把乘号换成除号：数字都在，构成不等价
    assert assess_target(GOOD_BIG_PAY.replace("×比例", "÷比例"),
                         BIG_PAY).status == MISSING_EVIDENCE
    # 删掉来源
    no_source = GOOD_BIG_PAY.replace("；来源：居民门诊待遇参数表。", "")
    assert assess_target(no_source, BIG_PAY).status == MISSING_EVIDENCE
    # 两行归属互换
    line1 = TargetRequirement("line.1", "第 1 行", "440.00", "explainable",
                              required_tokens=("医保范围内",))
    line2 = TargetRequirement("line.2", "第 2 行", "400.00", "explainable",
                              required_tokens=("医保范围内",))
    swapped = "\n".join(["- 第 1 行 400.00 元；医保范围内 360.00 元。",
                          "- 第 2 行 440.00 元；医保范围内 440.00 元。"])
    assert undelivered(swapped, [line1, line2]) == ["line.1", "line.2"]


def test_d8_valid_answers_are_accepted():
    """正例必须通过，避免用"全部拒绝"凑负例。"""
    precision = "- 第 1 行；本行费用 10.00 元＝单价 80 元×数量 0.125；医保范围内 10.00 元；按原单记录。"
    assert assess_target(precision, TargetRequirement(
        "precision.line1", "第 1 行", "10.00", "explainable",
        required_values=("0.125",), required_tokens=("×数量",),
        source_record=True)).status == REASON_EXPLAINED

    honest_gap = "- 费用总金额 60.00 元；本项金额不符，算法待补全。"
    assert assess_target(honest_gap, TargetRequirement(
        "precision.fee_all", "费用总金额", "60.00", "missing")).delivered is True

    assert assess_target(GOOD_BIG_PAY, BIG_PAY).status == REASON_EXPLAINED


def test_d9_rounding_mutated_equation_fails():
    """R2 回归：全局小数压缩把 0.125 压成 0.13 后等式不成立，必须失败。"""
    requirement = TargetRequirement(
        "precision.line1", "第 1 行", "10.00", "explainable",
        required_values=("0.125",), required_tokens=("×数量",))
    mutated = "- 第 1 行 10.00 元＝单价 80 元×数量 0.13；医保范围内 10.00 元。"
    assert assess_target(mutated, requirement).status == MISSING_EVIDENCE
    assert Decimal("80") * Decimal("0.125") == Decimal("10.00")


def test_d10_unexplained_candidate_appended_fails():
    """R3 回归：正文夹带不可解释候选公式（含"计算："或候选比例）必须失败。"""
    requirement = TargetRequirement(
        "precision.fee_all", "费用总金额", "60.00", "missing",
        forbidden_tokens=("本段基金支付＝100.00×0.5", "计算："))
    leaked = "- 费用总金额 60.00 元；仅账面列示。计算：本段基金支付＝100.00×0.5＝50.00 元。"
    assert assess_target(leaked, requirement).delivered is False


def test_summary_groups_by_target_id_not_label():
    """相同中文标签也必须按目标 ID 统计，不能合并。"""
    a = TargetRequirement("resident.fee_in", "医疗保险范围内金额", "1117.10", "explainable",
                          required_tokens=("＋",), required_values=("629.10",),
                          source_record=True)
    b = TargetRequirement("employee.fee_in", "医疗保险范围内金额", "2400.00", "explainable",
                          required_tokens=("＋",), required_values=("1800",),
                          source_record=True)
    answer = "- 医疗保险范围内金额 2400.00 元；构成：1800.00＋600.00＝2400.00 元；按原单记录。"
    summary = acceptance_summary(answer, [a, b])
    assert "resident.fee_in" in summary[MISSING_EVIDENCE]
    assert "employee.fee_in" in summary[REASON_EXPLAINED]
