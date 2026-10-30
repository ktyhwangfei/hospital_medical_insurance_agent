"""大病二次保障与医疗救助：年度分段、补助顺序和不确定性。"""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.domain.insurance.fee_decomposition import RoundingMode, SecondaryCoverageContext
from src.runtime.policy_qa.fee_decomposition.secondary_coverage import decompose_secondary_coverage
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_special_mz_golden import _snapshot_djh814


def snapshot(civil_type="0", cumulative="40000", post=False, civil_total="0"):
    original = _snapshot_djh814()
    return replace(original, person=replace(original.person, civil_type=civil_type),
        observed=replace(original.observed, retire_officer_pay=Decimal("0")),
        secondary_coverage=SecondaryCoverageContext(
            big_ill_scope_total=Decimal(cumulative) if cumulative is not None else None,
            civil_fund_payment_total=Decimal(civil_total) if civil_total is not None else None,
            is_post_trade=post, evidence_status="confirmed"))


def calculate(snap, one="100", two="0", out=None):
    return decompose_secondary_coverage(snap,
        self_pay_1=Decimal(one) if one is not None else None,
        proportional_self_pay_2=Decimal(two) if two is not None else None,
        total_out_scope=Decimal(out if out is not None else two))


@pytest.mark.parametrize("mode", list(RoundingMode))
@pytest.mark.parametrize("one,two", [("0.005", "0"), ("0.006", "0.006")])
def test_fractional_cent_bases_need_confirmed_precision_policy(mode, one, two):
    snap = replace(snapshot(civil_type="25", cumulative="20000"), rounding_mode=mode)
    result = calculate(snap, one, two)
    assert result.big_ill_pay is None
    assert result.civil_in is None
    assert result.personal_payable is None
    assert "SECONDARY_AMOUNT_PRECISION_UNCONFIRMED" in {u.code for u in result.uncertainties}


def test_fractional_cent_aid_cap_room_cannot_create_half_cent_payment():
    result = calculate(snapshot(civil_type="2364", cumulative="20000", civil_total="159999.995"))
    assert result.civil_in is None
    assert "CIVIL_AMOUNT_PRECISION_UNCONFIRMED" in {u.code for u in result.uncertainties}


def test_fractional_cent_out_scope_blocks_only_personal_payable():
    result = calculate(snapshot(civil_type="25", cumulative="20000"), out="0.005")
    assert result.big_ill_pay == Decimal("65")
    assert result.civil_in == Decimal("35")
    assert result.personal_payable is None


def test_814_after_supplements_and_annual_post_snapshot():
    snap = snapshot(cumulative="36710.69", post=True)
    snap = replace(snap, observed=replace(snap.observed,
        big_ill_pay=Decimal("23.62"), feein_db_pay=Decimal("23.62"), feeout_db_pay=Decimal("0"),
        civil_in=Decimal("0"), feein_maf_pay=Decimal("0"), feeout_maf_pay=Decimal("0")))
    result = calculate(snap, one="52.50")
    assert result.big_ill_pay == Decimal("31.50")
    assert result.civil_in == Decimal("0")
    assert result.personal_payable == Decimal("21.00")
    assert next(f for f in result.fields if f.field_code == "BIG_ILL_PAY").check_status.value == "mismatched"


@pytest.mark.parametrize("prior,amount,expected", [
    ("30304", "100", "0"), ("30394", "100", "54"),
    ("80354", "100", "65"), ("80404", "100", "70")])
def test_deductible_and_50000_excess_band_boundaries(prior, amount, expected):
    assert calculate(snapshot(cumulative=prior), one=amount).big_ill_pay == Decimal(expected)


def test_assistance_identity_halves_threshold_and_adds_five_points():
    result = calculate(snapshot(civil_type="2364", cumulative="15202"))
    assert result.big_ill_pay == Decimal("65")
    assert result.civil_in == Decimal("29.75")  # 35 × 门特住院档85%
    assert result.personal_payable == Decimal("5.25")


def test_690_full_aid_after_db_matches_real_sample():
    result = calculate(snapshot(civil_type="25", cumulative="17306.70", post=True), one="972.40")
    assert result.big_ill_pay == Decimal("632.06")
    assert result.civil_in == Decimal("340.34")
    assert result.personal_payable == 0


def test_688_cent_rounding_uses_book_bucket_and_recalculates_downstream():
    snap = snapshot(civil_type="25", cumulative="23491.42", post=True)
    snap = replace(snap, observed=replace(snap.observed,
        big_ill_pay=Decimal("226.96"), feein_db_pay=Decimal("181.53"), feeout_db_pay=Decimal("45.43"),
        civil_in=Decimal("122.21"), feein_maf_pay=Decimal("97.74"), feeout_maf_pay=Decimal("24.47"),
        xjzf=Decimal("0"), zhzf=Decimal("0")))
    result = calculate(snap, one="279.27", two="69.90")
    assert result.big_ill_pay == Decimal("226.96")
    assert result.civil_in == Decimal("122.21")
    assert result.personal_payable == 0
    assert all(field.check_status.value == "matched" for field in result.fields)
    adopted = next(calc for calc in result.calculations if calc.calculation_id == "calc.secondary.feeout_db_pay")
    assert adopted.result == "45.43"
    assert adopted.rounding_rule == "settlement_record"
    assert Decimal(adopted.unrounded_result) == Decimal("45.435")
    assert adopted.operands[-1].ref == "fact.secondary.book.feeout_db_pay"


@pytest.mark.parametrize("book", [None, "45.42", "45.431", "-0.01", "NaN"])
def test_missing_invalid_or_larger_difference_is_not_adopted(book):
    snap = snapshot(civil_type="25", cumulative="20000")
    snap = replace(snap, observed=replace(snap.observed,
        feeout_db_pay=Decimal(book) if book is not None else None))
    result = calculate(snap, one="279.27", two="69.90")
    field = next(field for field in result.fields if field.field_code == "FEEOUT_DB_PAY")
    assert field.calculated_amount == "45.44"
    assert field.check_status.value != "matched"


def test_aid_adoption_cannot_exceed_remaining_annual_cap():
    snap = snapshot(civil_type="2364", cumulative="0", civil_total="159990")
    snap = replace(snap, observed=replace(snap.observed,
        feein_maf_pay=Decimal("6.01"), feeout_maf_pay=Decimal("4.00")))
    result = calculate(snap, one="60", two="40")
    assert result.civil_in == Decimal("10.00")
    assert next(field for field in result.fields if field.field_code == "FEEIN_MAF_PAY").check_status.value == "mismatched"


def test_cent_book_amount_cannot_enable_an_unentered_payment_branch():
    snap = snapshot(civil_type="25", cumulative="0")
    snap = replace(snap, observed=replace(snap.observed, feeout_db_pay=Decimal("0.01")))
    result = calculate(snap, one="100", two="20")
    assert result.big_ill_pay == 0
    assert next(field for field in result.fields if field.field_code == "FEEOUT_DB_PAY").check_status.value == "mismatched"


def test_proportional_advance_qualifies_but_fully_excluded_amount_does_not():
    result = calculate(snapshot(civil_type="25", cumulative="20000"), one="100", two="20", out="50")
    assert result.big_ill_pay == Decimal("78")
    assert result.civil_in == Decimal("42")
    assert result.personal_payable == Decimal("30")


def test_inpatient_aid_cap_uses_prior_paid_and_distributes_remaining_room():
    result = calculate(snapshot(civil_type="2364", cumulative="0", civil_total="159990"), one="60", two="40")
    assert result.big_ill_pay == 0
    assert result.civil_in == Decimal("10")
    assert result.personal_payable == Decimal("90")


@pytest.mark.parametrize("civil_type", ["25", "26", "336001"])
def test_uncapped_aid_does_not_require_annual_aid_payment(civil_type):
    result = calculate(snapshot(civil_type=civil_type, cumulative="0", civil_total=None))
    assert result.civil_in == (Decimal("85") if civil_type == "336001" else Decimal("100"))


@pytest.mark.parametrize("civil_type", [None, "999"])
def test_unknown_identity_is_not_assumed_non_assisted(civil_type):
    result = calculate(snapshot(civil_type=civil_type))
    assert result.big_ill_pay is None
    assert result.civil_in is None
    assert result.uncertainties


def test_missing_cumulative_blocks_nonzero_db_base_but_not_no_aid_identity():
    result = calculate(snapshot(cumulative=None))
    assert result.big_ill_pay is None
    assert result.civil_in == 0
    assert result.personal_payable is None


def test_zero_base_does_not_require_annual_cumulative():
    result = calculate(snapshot(cumulative=None), one="0")
    assert result.big_ill_pay == 0


def test_missing_basic_payment_does_not_take_book_amount_as_calculated_base():
    result = calculate(snapshot(), one=None)
    assert result.big_ill_pay is None
    assert result.personal_payable is None


def test_rules_before_2023_are_unavailable_not_silently_zero():
    result = calculate(replace(snapshot(), settle_date=date(2022, 12, 31)))
    assert result.big_ill_pay is None
    assert any(u.code == "SECONDARY_POLICY_NOT_EFFECTIVE" for u in result.uncertainties)


def test_post_snapshot_smaller_than_current_base_is_not_a_zero_prior():
    result = calculate(snapshot(cumulative="50", post=True), one="100")
    assert result.big_ill_pay is None
    assert any("CUMULATIVE" in u.code for u in result.uncertainties)


def test_post_aid_total_at_cap_cannot_force_match_to_current_target():
    for book in ("10", "20"):
        snap = snapshot(civil_type="2364", cumulative="0", post=True, civil_total="160000")
        snap = replace(snap, secondary_coverage=replace(snap.secondary_coverage, big_ill_scope_total=Decimal("200")),
                       observed=replace(snap.observed, civil_in=Decimal(book)))
        result = calculate(snap, one="200")
        assert result.civil_in is None
        assert any(u.code == "CIVIL_CAP_PRIOR_UNVERIFIABLE" for u in result.uncertainties)


def test_unknown_excluded_amount_does_not_block_known_db_base():
    result = decompose_secondary_coverage(snapshot(), self_pay_1=Decimal("100"),
        proportional_self_pay_2=Decimal("0"), total_out_scope=None)
    assert result.big_ill_pay == Decimal("60")
    assert result.personal_payable is None


def test_zero_aid_base_does_not_require_cumulative():
    result = calculate(snapshot(civil_type="2364", cumulative=None, civil_total=None), one="0")
    assert result.civil_in == 0
    assert result.personal_payable == 0


def test_unmodeled_other_supplement_is_not_silently_ignored():
    snap = replace(snapshot(), observed=replace(snapshot().observed, retire_officer_pay=Decimal("30")))
    result = calculate(snap)
    assert result.big_ill_pay is None
    assert any(u.code == "OTHER_SUPPLEMENT_RULE_UNCONFIRMED" for u in result.uncertainties)


def test_post_trade_derived_prior_has_no_scope_uncertainty():
    """交易后派生累计只用于分段定位，不再作为用户可见的待核实事项。"""
    result = calculate(snapshot(cumulative="40000", post=True), one="100")
    assert result.big_ill_pay is not None
    assert not any(u.code == "DB_PRIOR_CUMULATIVE_SCOPE_UNCONFIRMED" for u in result.uncertainties)


def test_post_trade_derived_prior_not_entering_bands_does_not_declare():
    """零基数不进入分段计算：即使交易后派生也不追加该声明。"""
    result = calculate(snapshot(cumulative="40000", post=True), one="0")
    assert result.big_ill_pay == 0
    assert not any(u.code == "DB_PRIOR_CUMULATIVE_SCOPE_UNCONFIRMED" for u in result.uncertainties)
