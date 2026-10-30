"""字段级核对单元测试（设计 §10 / §14 核对矩阵）。"""
from __future__ import annotations

from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    BranchOutcome,
    CheckStatus,
    CheckType,
    ExplanationLevel,
)
from src.runtime.policy_qa.fee_decomposition.reconciliation import (
    ELIGIBILITY_CONFLICT_REASON,
    coverage_counts,
    identity_field,
    overall_reconciliation_status,
    reconcile_field,
)


def test_matched_exact_zero_difference():
    f = reconcile_field("T_BigPay", "大额支付", CheckType.INDEPENDENT_RECALCULATION,
                        Decimal("100.00"), Decimal("100.00"))
    assert f.check_status == CheckStatus.MATCHED
    assert Decimal(f.difference) == 0
    assert f.explanation_level == ExplanationLevel.AMOUNT_RECONCILED


def test_one_cent_difference_kept_mismatched():
    # 一分钱差异保留，不自动抹平；difference = calculated - observed
    f = reconcile_field("T_BigPay", "大额支付", CheckType.INDEPENDENT_RECALCULATION,
                        Decimal("100.00"), Decimal("99.99"))
    assert f.check_status == CheckStatus.MISMATCHED
    assert f.difference == "0.01"


def test_no_backfill_from_observed():
    # 禁止反推：计算缺失时不用观测值回填，calculated 保持 None
    f = reconcile_field("T_FirstPay", "起付", CheckType.INDEPENDENT_RECALCULATION,
                        None, Decimal("100.00"), BranchOutcome.UNKNOWN)
    assert f.check_status == CheckStatus.NOT_VERIFIABLE
    assert f.calculated_amount is None
    assert f.explanation_level == ExplanationLevel.OBSERVED_ONLY


def test_unknown_observed_is_not_zero():
    f = reconcile_field("T_BCPay", "退休补助", CheckType.INDEPENDENT_RECALCULATION,
                        Decimal("50.00"), None)
    assert f.check_status == CheckStatus.NOT_VERIFIABLE
    assert f.reason_code == "OBSERVED_AMOUNT_UNKNOWN"
    assert f.observed_amount is None


def test_not_applicable_with_nonzero_observed_conflict():
    f = reconcile_field("T_BCPay", "退休补助", CheckType.INDEPENDENT_RECALCULATION,
                        Decimal("0"), Decimal("8.00"), BranchOutcome.NOT_APPLICABLE)
    assert f.check_status == CheckStatus.NOT_APPLICABLE
    assert f.reason_code == ELIGIBILITY_CONFLICT_REASON
    assert f.difference == "-8.00"


def test_not_applicable_zero_observed_no_conflict():
    f = reconcile_field("T_BCPay", "退休补助", CheckType.INDEPENDENT_RECALCULATION,
                        Decimal("0"), Decimal("0.00"), BranchOutcome.NOT_APPLICABLE)
    assert f.check_status == CheckStatus.NOT_APPLICABLE
    assert f.reason_code == "NOT_APPLICABLE"


def test_identity_check_uses_observed_components_only():
    # 混合事实核对：恒等式由账面观测分量构成，只能标 identity_check
    f = identity_field("T_FundPay", "基金合计", Decimal("100.00"),
                       (Decimal("70.00"), Decimal("30.00")))
    assert f.check_type == CheckType.IDENTITY_CHECK
    assert f.check_status == CheckStatus.MATCHED
    incomplete = identity_field("T_FundPay", "基金合计", Decimal("100.00"),
                                (Decimal("70.00"), None))
    assert incomplete.check_status == CheckStatus.NOT_VERIFIABLE


def test_overall_status_rules():
    matched = reconcile_field("A", "a", CheckType.DETAIL_AGGREGATION,
                              Decimal("1.00"), Decimal("1.00"))
    nv = reconcile_field("B", "b", CheckType.DETAIL_AGGREGATION, None, Decimal("1.00"))
    mm = reconcile_field("C", "c", CheckType.DETAIL_AGGREGATION,
                         Decimal("1.00"), Decimal("2.00"))
    assert overall_reconciliation_status((matched,)) == "matched"
    assert overall_reconciliation_status((matched, nv)) == "not_verifiable"
    assert overall_reconciliation_status((matched, nv, mm)) == "mismatched"


def test_coverage_counts():
    matched_ind = reconcile_field("A", "a", CheckType.INDEPENDENT_RECALCULATION,
                                  Decimal("1.00"), Decimal("1.00"))
    nv = reconcile_field("B", "b", CheckType.DETAIL_AGGREGATION, None, Decimal("1.00"))
    cov = coverage_counts((matched_ind, nv))
    assert cov == {
        "target_field_count": 2,
        "independently_explained_count": 1,
        "amount_reconciled_count": 1,
        "observed_only_count": 1,
    }


def test_decimal_to_str_preserves_negative_zero_sign():
    # 负零必须带符号输出：恒等式/差额计算记录的减项取负后，
    # 公式渲染层按值是否以 "-" 开头决定 ＋/－，丢符号会渲染成加号
    from src.domain.insurance.fee_decomposition import decimal_to_str

    assert decimal_to_str(Decimal("-0.00")) == "-0.00"
    assert decimal_to_str(Decimal("0.00").copy_negate()) == "-0.00"
    # 正常零不受影响
    assert decimal_to_str(Decimal("0.00")) == "0.00"
    assert decimal_to_str(Decimal("0")) == "0"
    # 注意：一元取负 -Decimal("0.00") 在十进制上下文中等同 0-0.00，本身即丢符号，
    # 因此减项取负一律用 copy_negate（见各链恒等式分量构造）
    assert not (-Decimal("0.00")).is_signed()


def test_identity_calculation_signed_zero_subtrahend_renders_minus():
    # 恒等式减项为零（如大额互助支付 0.00）：分量取负必须保留符号，
    # 计算记录与公开公式都渲染为减项而非"＋ 0.00"
    from src.domain.insurance.fee_decomposition import CalculationOperand, decimal_to_str
    from src.runtime.policy_qa.fee_decomposition.formula_text import calculation_formula
    from src.runtime.policy_qa.fee_decomposition.reconciliation import identity_calculation

    calc = identity_calculation(
        "calc.identity.xjzf_channel", "identity_xjzf_channel_v1",
        (CalculationOperand("ZJE", "6000.00"),
         CalculationOperand("DEGWYZHF", decimal_to_str(Decimal("0.00").copy_negate()))))
    assert calc.operands[1].value == "-0.00"
    formula = calculation_formula(calc, [
        {"display_name": "总费用", "value": "6000.00"},
        {"display_name": "大额互助支付", "value": calc.operands[1].value},
    ])
    assert formula is not None
    assert "－ 大额互助支付 0.00" in formula
    assert "＋ 大额互助支付" not in formula
