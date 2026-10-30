from decimal import Decimal

from src.runtime.policy_qa.fee_decomposition.public_view import build_public_view_dict
from src.runtime.policy_qa.fee_decomposition.result import CalculationRecordModel, CalculationOperandModel
from src.runtime.policy_qa.fee_decomposition.fee_items import FeeItemExplanation, FeeItemDecision
from src.runtime.policy_qa.fee_decomposition.public_view import to_public_contract_dict
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_catalog_split import _run, _drug_item, _drug_entry
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_public_view import _result, _field


def public(result):
    return build_public_view_dict(result, summary_text='', summary_source='template')


def test_verified_calculation_cannot_explain_an_unbalanced_field():
    field = _field().model_copy(update={'check_status': 'mismatched', 'difference': '1', 'calculation_refs': ['calc.pay']})
    calc = CalculationRecordModel(calculation_id='calc.pay', formula_id='f', formula_version='v1', result='60')
    view = public(_result(fields=[field]).model_copy(update={'calculations': [calc]}))
    assert view['fields'][0]['explainable'] is False
    assert view['calculations'][0]['explainable'] is False


def test_observed_passthrough_does_not_prove_independent_calculation():
    field = _field().model_copy(update={'calculation_refs': ['calc.deductible.observed']})
    calc = CalculationRecordModel(calculation_id='calc.deductible.observed', formula_id='observed_deductible_passthrough_v1', formula_version='v1', result='60')
    assert public(_result(fields=[field]).model_copy(update={'calculations': [calc]}))['fields'][0]['explainable'] is False


def test_row_requires_all_three_amounts_to_match_not_only_total():
    split = _run(_drug_item(fee_in=Decimal('89'), fee_out=Decimal('11'), self_pay_2=Decimal('10')),
                 _drug_entry(sflb='乙', self_pay_ratio=Decimal('.1')))
    row = public(_result().model_copy(update={'fee_items': list(split.explanations)}))['fee_items'][0]
    assert row['explainable'] is False
    assert [check['check_status'] for check in row['reconciliations']] == ['mismatched', 'mismatched', 'matched']


def test_matched_row_exposes_classification_and_actual_ncp_comparison():
    split = _run(_drug_item(fee_in=Decimal('80'), fee_out=Decimal('20'), self_pay_2=Decimal('20')),
                 _drug_entry(sflb='乙', self_pay_ratio=Decimal('.1'), a_ypbs=True, a_mzxj=Decimal('50'), a_xbbl=Decimal('.2')))
    row = public(_result().model_copy(update={'fee_items': list(split.explanations)}))['fee_items'][0]
    assert row['explainable'] is True
    assert row['classification_label'] == '乙类'
    assert row['centralized_procurement'] is True
    check = next(check for check in row['decision_path'] if check['code'] == 'ncp_price_le_limit')
    assert (Decimal(check['actual']), Decimal(check['expected']), check['outcome']) == (Decimal('100'), Decimal('50'), 'false')
    assert row['ratio_basis'] == '本行费用金额'


def test_full_inclusion_has_zero_self_pay_and_does_not_invent_a_drug_class():
    split = _run(_drug_item(fee_in=Decimal('100'), fee_out=Decimal('0'), self_pay_2=Decimal('0')), _drug_entry(sflb='0301'))
    row = public(_result().model_copy(update={'fee_items': list(split.explanations)}))['fee_items'][0]
    assert row['explainable'] is True
    assert row['calculated_self_pay_2'] == '0'
    assert row['classification_label'] != '甲类'


def test_source_confirmation_is_separate_from_amount_match():
    calc = CalculationRecordModel(calculation_id='calc.pay', formula_id='ordinary_segment_pay_v1', formula_version='v1',
        result='60.00', rounding_rule='explicit:round_half_up(待确认)',
        operands=[CalculationOperandModel(ref='fee', value='100'), CalculationOperandModel(ref='ratio', value='.6')])
    field = _field().model_copy(update={'calculation_refs': ['calc.pay']})
    view = public(_result(fields=[field]).model_copy(update={'calculations': [calc]}))
    assert view['fields'][0]['explainable'] is True
    assert view['calculations'][0]['explainable'] is True
    assert view['calculations'][0]['verification_status'] == 'unverified'


def test_matched_downstream_cannot_hide_a_mismatched_upstream():
    prior = _field().model_copy(update={'field_code': 'prior', 'calculated_amount': '100', 'observed_amount': '99', 'check_status': 'mismatched', 'calculation_refs': ['calc.prior']})
    downstream = _field().model_copy(update={'calculation_refs': ['calc.pay']})
    calculations = [CalculationRecordModel(calculation_id='calc.prior', formula_id='f', formula_version='v1', result='100'),
        CalculationRecordModel(calculation_id='calc.pay', formula_id='f', formula_version='v1', result='60', operands=[CalculationOperandModel(ref='calc.prior', value='100')])]
    view = public(_result(fields=[prior, downstream]).model_copy(update={'calculations': calculations}))
    assert all(not field['explainable'] for field in view['fields'])


def test_unknown_procurement_flag_is_not_confirmed_non_procurement():
    split = _run(_drug_item(fee_in=Decimal('100'), fee_out=Decimal('0'), self_pay_2=Decimal('0')), _drug_entry(a_ypbs_known=False))
    row = public(_result().model_copy(update={'fee_items': list(split.explanations)}))['fee_items'][0]
    assert row['centralized_procurement'] is None
    assert row['explainable'] is False
    assert row['formulas'] == [] and row['decision_path'] == []


def test_settlement_price_limit_return_does_not_invent_ncp_price_branch():
    split = _run(_drug_item(sp_scale=Decimal('60'), medic_l=Decimal('.1'), fee_in=Decimal('54'), fee_out=Decimal('46'), self_pay_2=Decimal('46')),
                 _drug_entry(sflb='乙', a_ypbs=True, a_mzxj=Decimal('50'), self_pay_ratio=Decimal('.2')))
    row = public(_result().model_copy(update={'fee_items': list(split.explanations)}))['fee_items'][0]
    assert row['explainable'] is True
    assert row['ratio_source'] == '明细结算时比例（正值优先）'
    assert row['ratio_basis'] == '限价内金额'
    assert 'ncp_price_le_limit' not in [step['code'] for step in row['decision_path']]


def test_row_differences_cannot_cancel_to_make_an_explainable_aggregate():
    rows = [FeeItemExplanation(line_id=str(i), status='calculated', observed_in_scope=str(89 + i * 2), observed_out_scope=str(11 - i * 2),
        observed_self_pay_2='10', calculated_in_scope='90', calculated_out_scope='10', calculated_self_pay_2='10') for i in range(2)]
    field = _field().model_copy(update={'field_code': 'T_FeeIn', 'observed_amount': '180', 'calculated_amount': '180', 'calculation_refs': ['calc.catalog.total_in_scope']})
    calc = CalculationRecordModel(calculation_id='calc.catalog.total_in_scope', formula_id='catalog_total_in_scope_v1', formula_version='v1', result='180',
        operands=[CalculationOperandModel(ref='calc.catalog.lines.in_scope', value='180')])
    view = public(_result(fields=[field]).model_copy(update={'calculations': [calc], 'fee_items': rows}))
    assert view['fields'][0]['check_status'] == 'matched'
    assert not view['fields'][0]['explainable']


def test_nested_decision_text_is_sanitized_and_malformed_amount_fails_closed():
    row = FeeItemExplanation(line_id='1', status='calculated', observed_in_scope='90', observed_out_scope='10', observed_self_pay_2='10',
        calculated_in_scope='90', calculated_out_scope='10', calculated_self_pay_2='10',
        decision_path=[FeeItemDecision(code='c', label='yb_mzjyxx', operator='eq', actual='yb_mzjyxx', expected='yb_mzjyxx', outcome='true')])
    result = _result().model_copy(update={'fee_items': [row]})
    view = to_public_contract_dict(result, summary_text='', summary_source='template', sanitize=lambda text: str(text).replace('yb_mzjyxx', '结算记录'))
    assert view['fee_items'][0]['decision_path'][0]['actual'] == '结算记录'
    for malformed in ('bad', 'NaN', 'Infinity'):
        broken = row.model_copy(update={'observed_in_scope': malformed})
        assert not public(result.model_copy(update={'fee_items': [broken]}))['fee_items'][0]['explainable']


def test_adapter_preserves_unknown_procurement_flag_without_changing_calculation_mapping():
    from src.adapters.data_supply.outpatient_decomposition_queries import _drug_entry
    from src.adapters.data_supply.record_query_mappings import DEFAULT_RECORD_QUERY_MAPPING as mapping
    from src.adapters.data_supply.settlement_record_queries import _k
    for raw, known, adopted in ((None, False, False), ('unexpected', False, False), ('0', True, False), ('1', True, True)):
        entry = _drug_entry(0, {_k(mapping, 'cat_drug_a_ypbs'): raw}, mapping, [])
        assert entry.a_ypbs_known is known
        assert entry.a_ypbs is adopted
        assert entry.a_ypbs_raw == raw


def test_matched_line_calculation_remains_available_when_aggregate_is_unbalanced():
    from dataclasses import asdict
    split = _run(_drug_item(fee_in=Decimal('90'), fee_out=Decimal('10'), self_pay_2=Decimal('10')), _drug_entry(sflb='乙', self_pay_ratio=Decimal('.1')))
    field = _field().model_copy(update={'field_code': 'T_FeeIn', 'observed_amount': '89', 'calculated_amount': '90', 'check_status': 'mismatched', 'calculation_refs': ['calc.catalog.total_in_scope']})
    result = _result(fields=[field]).model_copy(update={'fee_items': list(split.explanations), 'calculations': [CalculationRecordModel(**asdict(calc)) for calc in split.calculations]})
    view = public(result)
    assert view['fee_items'][0]['explainable'] is True
    assert view['fields'][0]['explainable'] is False
    assert next(calc for calc in view['calculations'] if calc['formula_id'] == 'catalog_self_pay_2_v1')['explainable'] is True


def test_omitted_procurement_metadata_cannot_claim_confirmed_non_procurement():
    from src.domain.insurance.fee_decomposition import DrugCatalogEntry
    fixture = _drug_entry()
    entry = DrugCatalogEntry(entry_id=fixture.entry_id, item_code=fixture.item_code, effective_date=fixture.effective_date, expiry_date=fixture.expiry_date, sflb=fixture.sflb)
    row = _run(_drug_item(), entry).explanations[0]
    assert row.centralized_procurement is None
