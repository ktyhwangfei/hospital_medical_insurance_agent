"""军残补助应沿实际剩余自付计算追溯，账面不符或缺引用仍阻断解释。"""
from dataclasses import replace
from decimal import Decimal

import pytest

from src.runtime.policy_qa.fee_decomposition.employee_outpatient_special import decompose_employee_outpatient_special
from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence
from src.runtime.policy_qa.fee_decomposition.fee_items import FeeItemExplanation
from src.runtime.policy_qa.fee_decomposition.public_view import build_public_view_dict
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_special_mz_golden import _snapshot_djh567


def _result567():
    snapshot = _snapshot_djh567()
    result = attach_evidence(decompose_employee_outpatient_special(snapshot), snapshot)
    result.fee_items = [FeeItemExplanation(line_id='1', status='calculated',
        total_fee='6000', observed_in_scope='6000', calculated_in_scope='6000',
        observed_out_scope='0', calculated_out_scope='0', observed_self_pay_2='0', calculated_self_pay_2='0')]
    return result


def _view(result):
    return build_public_view_dict(result, summary_text='', summary_source='template')


def test_567_military_residuals_link_to_actual_upstream_calculations():
    public = _view(_result567())
    calculations = {calc['calculation_id']: calc for calc in public['calculations']}
    pool = calculations['calc.pool.self_pay_residual']
    large = calculations['calc.large.self_pay_residual']
    assert Decimal(pool['result']) == Decimal('211.50')
    assert [op['calculation_ref'] for op in pool['operands']] == ['calc.pool.self_pay', 'calc.rsup.pool']
    assert Decimal(large['result']) == 0
    assert large['operands'][0]['calculation_ref'] == 'calc.large.self_pay'
    assert '未进入大额段' in calculations['calc.large.self_pay']['formula']
    assert calculations['calc.dvet.amount']['explainable'] is True
    field = next(field for field in public['fields'] if field['field_code'] == 'JCZHF')
    assert field['explainable'] is True
    assert Decimal(field['calculated_amount']) == Decimal(field['observed_amount']) == Decimal('1511.50')
    assert {'calc.pool.self_pay_residual', 'calc.large.self_pay_residual', 'calc.rsup.pool'} <= set(field['calculation_refs'])


@pytest.mark.parametrize('code', ['TCZIF', 'BCZHF', 'DEGWYZIF'])
def test_mismatched_upstream_still_blocks_military_explanation(code):
    result = _result567()
    result.fields = [field.model_copy(update={'observed_amount': str(Decimal(field.calculated_amount) + 1),
        'difference': '-1', 'check_status': 'mismatched'}) if field.field_code == code else field for field in result.fields]
    assert next(field for field in _view(result)['fields'] if field['field_code'] == 'JCZHF')['explainable'] is False


def test_missing_residual_calculation_still_blocks_military_explanation():
    result = _result567()
    result.calculations = [calc for calc in result.calculations if calc.calculation_id != 'calc.pool.self_pay_residual']
    assert next(field for field in _view(result)['fields'] if field['field_code'] == 'JCZHF')['explainable'] is False


def test_employed_military_uses_original_self_pay_without_retirement_subtraction():
    snapshot = _snapshot_djh567()
    snapshot = replace(snapshot, person=replace(snapshot.person, cblb='11', retirement_category=None))
    result = decompose_employee_outpatient_special(snapshot)
    calculations = {calc.calculation_id: calc for calc in result.calculations}
    assert [op.ref for op in calculations['calc.dvet.amount'].operands][1:3] == ['calc.pool.self_pay', 'calc.large.self_pay']
    assert 'calc.pool.self_pay_residual' not in calculations
    assert 'calc.large.self_pay_residual' not in calculations


def test_large_segment_residual_links_to_its_retirement_supplement():
    snapshot = _snapshot_djh567()
    snapshot = replace(snapshot, cycle=replace(snapshot.cycle, prior_annual_pool_fund_payment=Decimal('100000')))
    result = decompose_employee_outpatient_special(snapshot)
    calculations = {calc.calculation_id: calc for calc in result.calculations}
    residual = calculations['calc.large.self_pay_residual']
    assert [op.ref for op in residual.operands] == ['calc.large.self_pay', 'calc.rsup.large']
    assert Decimal(residual.result) == Decimal(calculations['calc.large.self_pay'].result) - Decimal(calculations['calc.rsup.large'].result)
