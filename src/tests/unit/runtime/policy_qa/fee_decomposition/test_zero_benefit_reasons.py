"""职工门诊零补助必须携带实际未命中条件，不能把未接线写成资格缺失。"""
from dataclasses import replace
from decimal import Decimal

import pytest

from src.runtime.policy_qa.fee_decomposition.employee_outpatient import decompose_employee_outpatient
from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence, input_id
from src.runtime.policy_qa.fee_decomposition.model_explanation import build_model_input
from src.runtime.policy_qa.fee_decomposition.public_view import to_public_contract_dict
from src.runtime.policy_qa.public_contract import FeeDecompositionPublic
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_employee_outpatient import _snapshot, _drug_item


def _result(**facts):
    snapshot = _snapshot()
    snapshot = replace(snapshot, person=replace(
        snapshot.person, is_disabled_veteran=None, public_medical_eligible=None, **facts))
    result = decompose_employee_outpatient(snapshot)
    return snapshot, attach_evidence(result, snapshot)


@pytest.mark.parametrize(('facts', 'field_code', 'reason', 'source_ref'), [
    ({'military_disability_level_code': '0'}, 'T_JCPay',
     'NO_MILITARY_DISABILITY_BENEFIT', 'fact.person.military_disability_level_code'),
    ({'public_medical_flag': '0', 'public_medical_treatment_code': '0'}, 'T_OfficalPay',
     'PUBLIC_MEDICAL_CHANNEL_NOT_SELECTED', 'fact.person.public_medical_treatment_code'),
    ({'public_medical_flag': '1'}, 'T_OfficalPay',
     'NOT_PUBLIC_MEDICAL', 'fact.person.public_medical_flag'),
])
def test_zero_source_code_returns_a_sourced_zero_branch(facts, field_code, reason, source_ref):
    _, result = _result(**facts)
    field = next(field for field in result.fields if field.field_code == field_code)
    assert Decimal(field.calculated_amount) == Decimal('0')
    assert field.check_status == 'not_applicable'
    assert field.reason_code == reason
    branch = next(branch for branch in result.branches if branch.reason_code == reason)
    actual = facts[source_ref.rsplit('.', 1)[-1]]
    assert branch.condition.actual_value == actual
    assert source_ref in branch.input_refs
    assert not any(field_code in gap.affected_fields for gap in result.uncertainties)
    public = FeeDecompositionPublic.model_validate(to_public_contract_dict(
        result, summary_text='', summary_source='template', sanitize=str))
    target = build_model_input(public, '残疾军人补助支付金额为什么是0' if field_code == 'T_JCPay'
                               else '单位补充医疗保险（原公疗）支付金额为什么是0')
    assert target.target_kind == 'summary_fields'
    assert [field.field_code for field in target.decomposition.fields] == [field_code]
    node = next(node for node in target.decomposition.formula_inputs
                if node.input_id == input_id(source_ref))
    assert node.value == actual and node.status == 'verified'
    assert any(condition.actual_display == actual for condition in target.decomposition.conditions)


@pytest.mark.parametrize('raw', [None, '', '3', '999'])
def test_missing_or_unknown_source_codes_remain_unknown(raw):
    _, result = _result(military_disability_level_code=raw, public_medical_treatment_code=raw)
    for code in ('T_JCPay', 'T_OfficalPay'):
        field = next(field for field in result.fields if field.field_code == code)
        assert field.calculated_amount is None
        assert field.check_status == 'not_verifiable'


@pytest.mark.parametrize(('raw', 'observed', 'code'), [
    ('military_disability_level_code', 'jc_pay', 'T_JCPay'),
    ('public_medical_treatment_code', 'official_pay', 'T_OfficalPay'),
])
def test_zero_channel_does_not_turn_book_conflict_into_a_match(raw, observed, code):
    snapshot = _snapshot()
    snapshot = replace(snapshot,
        person=replace(snapshot.person, is_disabled_veteran=None, public_medical_eligible=None,
                       **{raw: '0'}),
        observed=replace(snapshot.observed, **{observed: Decimal('10.00')}))
    result = decompose_employee_outpatient(snapshot)
    field = next(field for field in result.fields if field.field_code == code)
    assert field.reason_code == 'ELIGIBILITY_CONFLICT_WITH_BOOK'


@pytest.mark.parametrize(('flag', 'raw', 'expected'), [
    ('is_disabled_veteran', 'military_disability_level_code', 'MILITARY_ELIGIBILITY_FACT_CONFLICT'),
    ('public_medical_eligible', 'public_medical_treatment_code', 'PUBLIC_MEDICAL_CHANNEL_CONFLICT'),
])
def test_zero_source_code_conflicting_with_positive_eligibility_stays_unknown(flag, raw, expected):
    snapshot = _snapshot()
    snapshot = replace(snapshot, person=replace(snapshot.person, **{flag: True, raw: '0'}))
    result = decompose_employee_outpatient(snapshot)
    assert any(gap.code == expected for gap in result.uncertainties)
    code = 'T_JCPay' if flag == 'is_disabled_veteran' else 'T_OfficalPay'
    field = next(field for field in result.fields if field.field_code == code)
    assert field.calculated_amount is None and field.check_status == 'not_verifiable'


def test_all_fund_channels_zero_still_produces_decimal_totals():
    snapshot = _snapshot(items=(_drug_item('100.00'),), has_other_fund_channels=None)
    snapshot = replace(snapshot,
        person=replace(snapshot.person, is_disabled_veteran=None, public_medical_eligible=None,
                       military_disability_level_code='0', public_medical_treatment_code='0'),
        observed=replace(snapshot.observed, fee_all=Decimal('100.00'), fee_in=Decimal('100.00'),
                         first_pay=Decimal('100.00'), big_pay=Decimal('0.00'),
                         big_self_pay=Decimal('0.00'), retire_officer_pay=Decimal('0.00'),
                         fund_pay=Decimal('0.00'), self_pay_all=Decimal('100.00')))
    result = decompose_employee_outpatient(snapshot)
    fields = {field.field_code: field for field in result.fields}
    assert Decimal(fields['T_FundPay'].calculated_amount) == Decimal('0')
    assert Decimal(fields['T_SelfPayAll'].calculated_amount) == Decimal('100')
