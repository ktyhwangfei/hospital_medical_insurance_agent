"""结算单标准名称、数据库绑定与布局共用同一份配置。"""
from decimal import Decimal

import pytest

from src.config.settlement_templates import get_settlement_template
from src.adapters.data_supply.settlement_template_bindings import bind_template_values, observed_template_amounts
from src.runtime.policy_qa.fee_decomposition.settlement_facts import build_outpatient_facts, build_special_mz_facts


def test_image_names_and_two_column_positions_are_exact():
    template = get_settlement_template('employee_outpatient')
    fields = {field.key: field for field in template.fields}
    assert len([field for field in template.fields if field.section == 'transaction']) == 19
    assert fields['fee_in'].label == '医疗保险范围内金额'
    assert fields['self_pay_1'].label == '个人支付自付（一）金额'
    assert fields['official_pay'].label == '单位补充医疗保险（原公疗）支付金额'
    assert (fields['fee_all'].row, fields['fee_all'].column) == (1, 1)
    assert (fields['personal_total'].row, fields['personal_total'].column) == (1, 2)
    assert fields['official_pay'].span == 2


@pytest.mark.parametrize('key', ['employee_outpatient', 'resident_outpatient', 'employee_special', 'resident_special'])
def test_four_chains_have_explicit_independent_templates(key):
    template = get_settlement_template(key)
    assert template.template_id == key
    assert all(field.evidence for field in template.fields)
    assert all(field.operation == 'unmapped' or field.column_keys or field.context_key for field in template.fields)


def test_facts_and_kernel_observations_use_the_same_binding():
    row = {'p_fundtype': '3', 't_feein': Decimal('1812.37'), 't_beyondbig': Decimal('0.00')}
    template = get_settlement_template('employee_outpatient')
    observed = observed_template_amounts(template, {'outpatient_trade_table': row})
    facts = build_outpatient_facts(row)
    display = {field.key: field for field in facts.display_template.fields}
    assert display['fee_in'].value == str(observed['fee_in']) == '1812.37'
    assert display['beyond_cap'].value == '0.00'
    assert display['cash_pay'].value is None
    assert display['cash_pay'].status == 'missing'


def test_database_column_override_is_honoured_without_label_matching():
    from src.adapters.data_supply.record_query_mappings import RecordQueryMapping
    template = get_settlement_template('employee_outpatient')
    mapping = RecordQueryMapping(columns={'op_fee_in': 'CustomFeeIn'})
    bound = bind_template_values(template, {'outpatient_trade_table': {'customfeein': '99.12', 't_feein': '800'}}, mapping)
    assert bound.values['fee_in'] == '99.12'


def test_special_fixed_variant_does_not_explain_patient_book_as_hospital_quota():
    facts = build_special_mz_facts(
        {'tczhf': '200.20', 'tczhf1': '210.60', 'tsbybn1': '1526', 'djh': '609'},
        {'fund_type': '3'}, fixed=True,
    )
    display = {field.key: field for field in facts.display_template.fields}
    assert facts.display_template.template_id == 'employee_special_fixed_kidney'
    assert display['pool_pay'].value == '200.20'
    assert display['pool_pay'].field_code is None
    assert display['hospital_pool_pay'].value == '210.60'
    assert display['hospital_pool_pay'].field_code == 'TCZHF'
    assert display['hospital_pool_pay'].scope == 'hospital_quota'


def test_unmapped_and_absent_fields_are_not_filled_with_zero_or_model_guesses():
    template = get_settlement_template('resident_special')
    bound = bind_template_values(template, {'outpatient_settlement_table': {}})
    assert all(value is None for value in bound.values.values())
    with pytest.raises(KeyError):
        get_settlement_template('unknown_chain')


def test_public_fields_and_question_targets_use_the_frozen_standard_name():
    from src.runtime.policy_qa.fee_decomposition.public_view import to_public_contract_dict
    from src.runtime.policy_qa.fee_decomposition.result import FieldExplanationModel
    from src.runtime.policy_qa.public_contract import FeeDecompositionPublic
    from src.runtime.policy_qa.fee_decomposition.model_explanation import resolve_target_fields
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_public_view import _result
    facts = build_outpatient_facts({'p_fundtype': '3', 't_feein': '1812.37'})
    result = _result().model_copy(update={'fields': [FieldExplanationModel(
        field_code='T_FeeIn', label='医保内费用', check_type='independent_recalculation',
        check_status='matched', observed_amount='1812.37', calculated_amount='1812.37',
        explanation_level='amount_reconciled')]})
    public = FeeDecompositionPublic.model_validate(to_public_contract_dict(result, summary_text='',
        summary_source='template', settlement_facts=facts, sanitize=str))
    assert public.fields[0].label == '医疗保险范围内金额'
    assert resolve_target_fields(public, '医疗保险范围内金额怎么算') == ['T_FeeIn']
    fixed = build_special_mz_facts({'tczhf': '200.20', 'tczhf1': '210.60'}, {'fund_type': '3'}, fixed=True)
    public = public.model_copy(update={'settlement_facts': fixed})
    assert resolve_target_fields(public, '统筹基金支付金额怎么算') == ['bill.pool_pay']


@pytest.mark.parametrize('question,expected', [
    ('费用总金额和医保范围内、范围外金额分别是多少，怎么算？',
     {'T_FeeAll', 'T_FeeIn', 'T_FeeOut'}),
    ('大病支付和自付二怎么算？', {'bill.big_ill_pay', 'T_SelfPay2'}),
    ('个人支付自付（二）金额和大额支付怎么算？', {'T_SelfPay2', 'T_BigPay'}),
])
def test_question_targets_combine_standard_names_and_aliases(question, expected):
    from src.runtime.policy_qa.fee_decomposition.public_view import to_public_contract_dict
    from src.runtime.policy_qa.public_contract import FeeDecompositionPublic
    from src.runtime.policy_qa.fee_decomposition.model_explanation import resolve_target_fields
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_public_view import _result, _field
    codes = ('T_FeeAll', 'T_FeeIn', 'T_FeeOut', 'T_SelfPay2', 'T_BigPay')
    result = _result(fields=[_field(field_code=code, label=code) for code in codes])
    facts = build_outpatient_facts({'p_fundtype': '3'})
    public = FeeDecompositionPublic.model_validate(to_public_contract_dict(
        result, summary_text='', summary_source='template', settlement_facts=facts, sanitize=str))

    assert set(resolve_target_fields(public, question)) == expected


@pytest.mark.parametrize('value', ['NaN', 'Infinity', 'invalid-money'])
def test_bad_source_amount_is_rejected_instead_of_becoming_an_available_bill_value(value):
    template = get_settlement_template('employee_outpatient')
    with pytest.raises(ValueError):
        bind_template_values(template, {'outpatient_trade_table': {'t_feein': value}})


def test_config_cannot_insert_sql_into_source_column_or_overlap_bill_positions():
    from pydantic import ValidationError
    from src.config.settlement_templates import SettlementDisplayTemplate, SettlementTemplateField
    template = get_settlement_template('employee_outpatient')
    field = next(field for field in template.fields if field.key == 'fee_in')
    with pytest.raises(ValidationError):
        SettlementTemplateField.model_validate({**field.model_dump(), 'column_keys': ['T_FeeIn; SELECT secret']})
    invalid = template.model_dump()
    invalid['fields'] = [field.model_dump(), {**field.model_dump(), 'key': 'collision', 'field_code': None, 'observed_attribute': None}]
    with pytest.raises(ValidationError):
        SettlementDisplayTemplate.model_validate(invalid)


def test_every_bound_field_declares_database_table_column_path():
    """映射必须能给出 库.表.字段，人工可核对；上下文/未映射字段明确留空。"""
    from src.adapters.data_supply.record_query_mappings import DEFAULT_RECORD_QUERY_MAPPING
    from src.adapters.data_supply.settlement_template_bindings import resolve_template_paths

    for template_id in ('employee_outpatient', 'resident_outpatient', 'employee_special', 'resident_special'):
        template = get_settlement_template(template_id)
        paths = resolve_template_paths(template, DEFAULT_RECORD_QUERY_MAPPING)
        for field in template.fields:
            if field.operation == 'unmapped':
                assert paths[field.key] == []
                continue
            assert paths[field.key], f'{template_id}.{field.key} 缺少物理路径'
            for path in paths[field.key]:
                assert path.startswith(f'{template.source_database}.'), path
                assert path.count('.') >= 2, path
    outpatient = resolve_template_paths(get_settlement_template('employee_outpatient'), DEFAULT_RECORD_QUERY_MAPPING)
    assert outpatient['personal_total'] == ['bjybdb.dbo.o_Trade.T_SelfPayAll']
    special = resolve_template_paths(get_settlement_template('employee_special'), DEFAULT_RECORD_QUERY_MAPPING)
    assert special['pool_pay'] == ['bjybdb.dbo.yb_mzjyxx.tczhf']
    assert special['feein_db'] == ['bjybdb.dbo.yb_mzjyxx.FEEIN_DB_PAY']
