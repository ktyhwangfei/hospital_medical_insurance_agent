"""Issue #82：定额与实际费用双口径，不能用基金观测值倒推个人支付。"""
from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from src.domain.insurance.fee_decomposition import KidneyFixedQuotaContext, SecondaryCoverageContext
from src.runtime.policy_qa.fee_decomposition.employee_special_fixed_kidney import decompose_kidney_fixed_quota
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_special_mz_golden import _snapshot_djh609


def kidney_snapshot():
    snapshot = _snapshot_djh609()
    return replace(snapshot,
        items=(replace(snapshot.items[0], item_code="XL04ADT002E001020304641"),),
        cycle=replace(snapshot.cycle, prior_cycle_in_scope_total=D("0"), prior_annual_pool_fund_payment=D("0")),
        person=replace(snapshot.person, civil_type="0"),
        secondary_coverage=SecondaryCoverageContext(big_ill_scope_total=D("0"), is_post_trade=False, evidence_status="confirmed"),
        observed=replace(snapshot.observed, tczhf=D("210.60"), tczif=D("15.40"),
            bczhf=D("7.70"), jczhf=D("653.85"), big_ill_pay=D("0"),
            civil_in=D("0"), feein_db_pay=D("0"), feeout_db_pay=D("0"),
            feein_maf_pay=D("0"), feeout_maf_pay=D("0"), retire_officer_pay=D("0")),
        kidney_fixed_quota=KidneyFixedQuotaContext(
            special_codes=("503",), designated_hospital_flag="1", quota_amount=D("1526"),
            medication_start=date(2024, 9, 19), medication_end=date(2024, 9, 25),
            cycle_start=date(2024, 9, 19),
            initial_self_pay_observed=D("1315.40"), agency_pay_observed=D("1457.15")))


def fields(result):
    return {field.field_code: field for field in result.fields}


def test_609_dual_amounts_and_personal_payment():
    result = decompose_kidney_fixed_quota(kidney_snapshot())
    values = fields(result)
    expected = {"TCZHF": "210.60", "TCZIF": "15.40", "BCZHF": "7.70",
        "JCZHF": "653.85", "GFYLBCHBX": "585.00", "PERSON_PAYABLE": "68.85",
        "GRZIF1": "1315.40", "AGENCY_PAY": "1457.15"}
    for key, value in expected.items():
        assert D(values[key].calculated_amount) == D(value)
        assert values[key].check_status == "matched"
    assert result.algorithm_version == "employee_special_fixed_kidney_v1"
    assert not result.answer_constraints.may_claim_full_explanation
    assert values["TCZHF"].check_type == "identity_check"
    assert fields(result)["QUOTA_AMOUNT"].calculated_amount is None


@pytest.mark.parametrize("flag", [None, "", "0"])
def test_designated_hospital_required(flag):
    snapshot = kidney_snapshot()
    snapshot = replace(snapshot, kidney_fixed_quota=replace(snapshot.kidney_fixed_quota, designated_hospital_flag=flag))
    result = decompose_kidney_fixed_quota(snapshot)
    assert result.execution_status == "unavailable"
    assert any(u.code == "FIXED_DESIGNATED_HOSPITAL_UNCONFIRMED" for u in result.uncertainties)


@pytest.mark.parametrize("code", ["503", "504"])
def test_both_transplant_codes(code):
    snapshot = kidney_snapshot()
    result = decompose_kidney_fixed_quota(replace(snapshot, kidney_fixed_quota=replace(snapshot.kidney_fixed_quota, special_codes=("506", code))))
    assert result.execution_status != "unavailable"


def test_unmapped_or_mixed_items_do_not_all_get_reduced_rate():
    snapshot = kidney_snapshot()
    result = decompose_kidney_fixed_quota(replace(snapshot, items=(replace(snapshot.items[0], item_code="UNKNOWN"),)))
    assert result.execution_status == "unavailable"
    assert any(u.code == "FIXED_MANAGED_SCOPE_UNCONFIRMED" for u in result.uncertainties)


def test_cross_year_medication_needs_split_snapshot():
    snapshot = kidney_snapshot()
    result = decompose_kidney_fixed_quota(replace(snapshot, kidney_fixed_quota=replace(snapshot.kidney_fixed_quota, medication_end=date(2025, 1, 1))))
    assert result.execution_status == "unavailable"
    assert any(u.code == "FIXED_PERIOD_SPLIT_UNCONFIRMED" for u in result.uncertainties)


def test_hospital_target_not_used_to_compute_itself():
    snapshot = kidney_snapshot()
    result = decompose_kidney_fixed_quota(replace(snapshot, observed=replace(snapshot.observed, tczhf=D("999"))))
    assert fields(result)["TCZHF"].calculated_amount == "210.60"
    assert fields(result)["TCZHF"].check_status == "mismatched"


def test_missing_quota_preserves_independent_patient_self_pay():
    snapshot = kidney_snapshot()
    result = decompose_kidney_fixed_quota(replace(snapshot, kidney_fixed_quota=replace(snapshot.kidney_fixed_quota, quota_amount=None)))
    assert D(fields(result)["GRZIF1"].calculated_amount) == D("1315.40")
    assert fields(result)["TCZHF"].calculated_amount is None
    assert not result.answer_constraints.may_claim_full_explanation


def test_record_start_cannot_stand_in_for_missing_cycle_start():
    snapshot = kidney_snapshot()
    result = decompose_kidney_fixed_quota(replace(snapshot,
        kidney_fixed_quota=replace(snapshot.kidney_fixed_quota, cycle_start=None)))
    assert result.execution_status == "unavailable"
    assert any(u.code == "FIXED_PERIOD_SPLIT_UNCONFIRMED" for u in result.uncertainties)


@pytest.mark.parametrize("quota,reason", [(D("100"), "FIXED_QUOTA_BELOW_SELF_PAY"),
    (D("101400"), "FIXED_POOL_CAP_SPLIT_UNCONFIRMED")])
def test_unconfirmed_quota_or_cap_split_never_fabricates_fund(quota, reason):
    snapshot = kidney_snapshot()
    result = decompose_kidney_fixed_quota(replace(snapshot,
        kidney_fixed_quota=replace(snapshot.kidney_fixed_quota, quota_amount=quota)))
    assert fields(result)["TCZHF"].calculated_amount is None
    assert any(u.code == reason for u in result.uncertainties)


def test_reduction_floor_is_zero_after_retirement_ratio():
    snapshot = kidney_snapshot()
    snapshot = replace(snapshot, institution=replace(snapshot.institution, h_level="10"),
        cycle=replace(snapshot.cycle, prior_cycle_in_scope_total=D("40000"), prior_cycle_deductible_paid=D("1300")))
    result = decompose_kidney_fixed_quota(snapshot)
    assert D(fields(result)["TCZIF"].calculated_amount) == D("0")


def test_unconfirmed_scope_preserves_708_source_amounts():
    snapshot = kidney_snapshot()
    result = decompose_kidney_fixed_quota(replace(snapshot,
        kidney_fixed_quota=replace(snapshot.kidney_fixed_quota, designated_hospital_flag=None)))
    assert fields(result)["TCZHF"].observed_amount == "210.60"
    assert fields(result)["PERSON_PAYABLE"].calculated_amount is None


def test_ordinary_source_scope_excludes_every_transplant_slot_with_null_safe_predicate(monkeypatch):
    from src.adapters.data_supply import outpatient_special_mz_queries as queries
    captured = []
    monkeypatch.setattr(queries, "_fetch_all", lambda connection, sql, params: captured.append((sql, params)) or [])
    result = queries.locate_special_mz_registration(object(), "609")
    assert result.data["match_status"] == "not_found"
    sql, params = captured[0]
    for key in ("tsb1", "tsb2", "tsb3"):
        assert f"COALESCE({key},'') NOT IN ('503','504')" in sql
    assert params == ["609", "12", "3"]


def test_fixed_cycle_subtracts_quota_instead_of_actual_amount():
    from src.adapters.data_supply.outpatient_special_fixed_kidney_queries import fixed_accumulation_settlement
    from src.adapters.data_supply.outpatient_special_mz_queries import derive_mz_cycle_context
    row = {"tsbybn": D("1520"), "tsbybn1": D("1526"), "tczhf": D("200.20"), "tczhf1": D("210.60"),
        "degwyzhf": D("0"), "dezhf1": D("0"), "ybnqfje": D("1300")}
    cycle, _ = derive_mz_cycle_context({"bqljybnje": D("1526"), "bqqfje": D("1300")},
        {"bnzqslj": D("1"), "bntczfje": D("210.60"), "bndezfje": D("0")},
        fixed_accumulation_settlement(row), special_record_start=None, settle_date=None)
    assert cycle.prior_cycle_in_scope_total == D("0")
    assert cycle.prior_annual_pool_fund_payment == D("0")


def test_large_cap_reached_disables_quota_even_if_no_new_large_payment():
    snapshot = kidney_snapshot()
    result = decompose_kidney_fixed_quota(replace(snapshot,
        cycle=replace(snapshot.cycle, prior_annual_large_fund_payment=D("500000"))))
    assert fields(result)["TCZHF"].calculated_amount is None
    assert any(u.code == "FIXED_LARGE_CAP_SPLIT_UNCONFIRMED" for u in result.uncertainties)


def test_public_payment_depending_on_given_quota_is_not_independent():
    snapshot = kidney_snapshot()
    snapshot = replace(snapshot, cycle=replace(snapshot.cycle, prior_cycle_deductible_paid=D("1300"), prior_cycle_in_scope_total=D("1300")),
        person=replace(snapshot.person, military_grade=None, military_grade_raw="0"),
        kidney_fixed_quota=replace(snapshot.kidney_fixed_quota, quota_amount=D("1400")))
    result = decompose_kidney_fixed_quota(snapshot)
    values = fields(result)
    assert D(values["GFYLBCHBX"].calculated_amount) == D("11.2")
    assert D(values["PERSON_PAYABLE"].calculated_amount) == D("42")
    for code in ("GFYLBCHBX", "PERSON_PAYABLE", "BIG_ILL_PAY", "CIVIL_IN"):
        assert values[code].check_type == "identity_check"
        assert "u.fixed.quota" in values[code].uncertainty_refs


def test_fixed_public_policy_does_not_apply_before_july_2012():
    snapshot = kidney_snapshot()
    snapshot = replace(snapshot, settle_date=date(2012, 5, 1),
        items=(replace(snapshot.items[0], fee_date=date(2012, 5, 1)),),
        kidney_fixed_quota=replace(snapshot.kidney_fixed_quota, medication_start=date(2012, 5, 1),
            medication_end=date(2012, 5, 7), cycle_start=date(2012, 5, 1)))
    result = decompose_kidney_fixed_quota(snapshot)
    assert result.execution_status == "unavailable"
    assert any(u.code == "FIXED_PUBLIC_POLICY_NOT_EFFECTIVE" for u in result.uncertainties)


def test_quota_balance_excludes_patient_out_of_scope_payment():
    snapshot = kidney_snapshot()
    snapshot = replace(snapshot, items=(replace(snapshot.items[0], fee=D("1530"), out_scope_fee=D("10")),),
        observed=replace(snapshot.observed, zje=D("1530"), ybw=D("10"), xjzf=D("78.85")))
    result = decompose_kidney_fixed_quota(snapshot)
    assert D(fields(result)["PERSON_PAYABLE"].calculated_amount) == D("78.85")
    assert fields(result)["QUOTA.balance"].check_status == "matched"
