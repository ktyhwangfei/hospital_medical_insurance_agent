from decimal import Decimal
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_catalog_split import _run, _drug_item, _drug_entry
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_catalog_split import _service_item, _service_entry, _material_item, _material_entry
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_public_view import _result, _field
from src.runtime.policy_qa.fee_decomposition.fee_items import FeeItemExplanation, attach_item_rows, project_item_explanation, _item_explanation
from src.runtime.policy_qa.fee_decomposition.settlement_facts import SettlementFactsView, label_facts
from src.runtime.policy_qa.fee_decomposition.public_view import to_public_contract_dict, _calculation_dependencies
from src.runtime.policy_qa.fee_decomposition.formula_text import calculation_formula
from src.runtime.policy_qa.fee_decomposition.formula_display import rounding_display
from src.runtime.policy_qa.fee_decomposition.result import BranchTraceModel, CalculationRecordModel, CalculationOperandModel


def test_partial_fee_row_has_real_ratio_and_outputs_without_changing_money():
    split = _run(_drug_item(), _drug_entry(sflb="有自付", self_pay_ratio=Decimal('0.1')))
    item = split.explanations[0]
    assert item.calculated_in_scope == '90.00'
    assert item.calculated_out_scope == '10.00'
    assert '0.1' in '\n'.join(item.formulas)
    assert '90.00' in '\n'.join(item.formulas)
    assert split.total_in_scope == Decimal('90.00')
    assert item.division_method == 'ratio'
    assert item.self_pay_ratio == '0.1'


def test_price_limit_row_explains_limit_quantity_and_ratio():
    split = _run(_drug_item(sp_scale=Decimal('60')), _drug_entry(sflb="有自付", self_pay_ratio=Decimal('0.1')))
    item = split.explanations[0]
    assert item.calculated_in_scope == '54.00'
    assert item.calculated_out_scope == '46.00'
    assert '60' in '\n'.join(item.formulas) and '0.1' in '\n'.join(item.formulas)
    assert item.division_method == 'limit'
    assert item.unit_price_limit == '60'
    assert item.self_pay_ratio == '0.1'


def test_missing_catalog_keeps_unknown_without_fake_formula():
    item = _run(_drug_item(), None).explanations[0]
    assert item.status == 'unknown'
    assert item.calculated_in_scope is None
    assert item.formulas == []
    assert item.division_method == 'unknown'


def test_service_limit_and_material_inclusion_expose_the_executed_method():
    limited = _run(_service_item(), _service_entry(sfxmdj='2', self_pay_ratio=Decimal('0'), unit_price_limit=Decimal('150'))).explanations[0]
    assert limited.division_method == 'limit'
    assert limited.unit_price_limit == '150'
    assert limited.self_pay_ratio is None  # 0 表示走限价，不表示 0% 自付。
    material = _run(_material_item(unit_price=Decimal('1000'), fee=Decimal('1000')), _material_entry()).explanations[0]
    assert material.division_method == 'ratio'
    assert Decimal(material.included_ratio) == Decimal('0.8')


def test_row_ids_do_not_merge_duplicate_items_and_sidecar_is_not_internal_schema():
    rows = [dict(xh='1', xmdm='same', xmmc='项目甲', zje='10.00'), dict(xh='2', xmdm='same', xmmc='项目甲', zje='20.00')]
    result = attach_item_rows(_result(), rows, special=True)
    assert [item.total_fee for item in result.fee_items] == ['10.00', '20.00']
    assert 'fee_items' not in result.model_dump()
    assert result.schema_version == '1.0'
    duplicate = attach_item_rows(result, [rows[0], rows[0]], special=True)
    assert all(item.status == 'unknown' for item in duplicate.fee_items)


def test_zero_numeric_line_id_is_valid_and_can_explain_no_benefit():
    result = _result().model_copy(update={'branches': [BranchTraceModel(step_id='flow.no_benefit_check', module_id='employee_outpatient', outcome='true')]})
    view = attach_item_rows(result, [dict(xh=0, zje='400.00')], special=True).fee_items[0]
    assert view.status == 'calculated'
    assert view.calculated_out_scope == '400.00'
    assert '医保外金额＝本行费用金额 400.00 元' in view.formulas[0]


def test_dictionary_names_follow_field_namespace():
    domains = {'fund': {'93': '无业居民'}, 'yllbss': {'12': '特殊门诊'}, '300': {'12': '门诊特殊病'}, '290': {'21': '退休'}}
    special = label_facts(SettlementFactsView(chain='special', medical_category='12', insurance_type='93', person_type='21'), domains)
    assert special.metadata_names == {'insurance_type': '无业居民', 'person_type': '退休', 'medical_category': '门诊特殊病'}
    ordinary = label_facts(SettlementFactsView(chain='outpatient', medical_category='12'), domains)
    assert ordinary.metadata_names['medical_category'] == '特殊门诊'


def test_all_new_text_leaves_pass_public_sanitizer():
    result = attach_item_rows(_result(), [dict(xh='1', xmmc='yb_mzjyxx', zje='0.00')], special=True)
    view = to_public_contract_dict(result, summary_text='', summary_source='template', sanitize=lambda value: str(value).replace('yb_mzjyxx','结算记录'))
    assert view['fee_items'][0]['item_name'] == '结算记录'


def test_military_formula_subtracts_retire_instead_of_multiplying_all_inputs():
    calc = CalculationRecordModel(calculation_id='c', formula_id='military_supplement_v1', formula_version='v1', result='40.00',
        operands=[CalculationOperandModel(ref=str(i), value=value) for i,value in enumerate(('100.00','20.00','0.5'))])
    text = calculation_formula(calc, [])
    assert '自付 100.00 元－退休补助 20.00 元' in text
    assert text.endswith('＝40.00 元')


def test_secondary_bucket_formula_divides_by_base_instead_of_multiplying_all_inputs():
    calc = CalculationRecordModel(calculation_id='c', formula_id='secondary_feein_db_pay_v1', formula_version='v1', result='20.00',
        operands=[CalculationOperandModel(ref=str(i), value=value) for i,value in enumerate(('100.00','200.00','40.00'))])
    text = calculation_formula(calc, [])
    assert '40.00 元×本桶合规自付 100.00 元÷本笔合规总基数 200.00 元' in text


def test_direct_inclusion_has_explicit_full_inclusion_condition_and_formula():
    item = _run(_drug_item(), _drug_entry()).explanations[0]
    assert '本行全部纳入医保内' in '\n'.join(item.formulas)
    assert any('无自付' in value for value in item.conditions)


def test_calculation_dependencies_show_actual_upstream_without_loop_or_guessing():
    def calc(key, *refs):
        return CalculationRecordModel(calculation_id=key, formula_id='f', formula_version='v1',
            operands=[CalculationOperandModel(ref=ref, value='10') for ref in refs])
    index = {'pay': calc('pay', 'base', 'missing'), 'base': calc('base', 'prior'), 'prior': calc('prior', 'base')}
    assert _calculation_dependencies(['pay', 'pay'], index) == ['prior', 'base', 'pay']


def test_public_total_formula_lists_each_actual_fee_row_contribution():
    result = _result().model_copy(update={
        'calculations': [CalculationRecordModel(calculation_id='calc.catalog.total_in_scope', formula_id='catalog_total_in_scope_v1', formula_version='v1', result='170.00')],
        'fee_items': [FeeItemExplanation(line_id='1', item_name='项目甲', calculated_in_scope='90.00', status='calculated'),
                      FeeItemExplanation(line_id='2', item_name='项目乙', calculated_in_scope='80.00', status='calculated')],
    })
    view = to_public_contract_dict(result, summary_text='', summary_source='template', sanitize=str)
    assert view['calculations'][0]['formula'] == '医保内费用合计＝项目甲（第1行） 90.00 元 ＋ 项目乙（第2行） 80.00 元＝170.00 元'


def test_rounding_uses_chinese_but_keeps_pending_condition():
    assert rounding_display('explicit:round_half_up(EOP-RND-001 待确认)') == '按本次配置：四舍五入到分(EOP-RND-001 待确认)'
    assert rounding_display(None) is None


def test_fixed_field_brief_distinguishes_total_fund_formula_from_field_amount():
    field = _field().model_copy(update={'field_code': 'TCZHF', 'label': '医院统筹基金', 'check_type': 'identity_check',
        'observed_amount': '0.00', 'calculated_amount': '0.00', 'calculation_refs': ['calc.fixed.hospital_fund']})
    calc = CalculationRecordModel(calculation_id='calc.fixed.hospital_fund', formula_id='fixed_quota_minus_original_self_pay', formula_version='v1', result='210.60',
        operands=[CalculationOperandModel(ref='quota', value='1530.00'), CalculationOperandModel(ref='self', value='1319.40')])
    result = _result().model_copy(update={'fields': [field], 'calculations': [calc]})
    view = to_public_contract_dict(result, summary_text='', summary_source='template', sanitize=str)
    assert view['fields'][0]['brief'] is None
    assert view['fields'][0]['calculated_amount'] == '0.00'
    assert not view['fields'][0]['explainable']
    assert '1530.00 元－定额范围原始自付 1319.40 元' in view['calculations'][0]['formula']


def test_resident_special_clamp_formula_rounds_before_applying_both_bounds():
    calc = CalculationRecordModel(calculation_id='c', formula_id='resident_special_big_pay_clamp_v1', formula_version='v1', result='0.01',
        operands=[CalculationOperandModel(ref=str(i), value=value) for i, value in enumerate(('100.00', '0.75', '39999.99', '40000'))])
    formula = calculation_formula(calc, [])
    assert '最大值（取整（基数 100.00 元×比例 0.75），－交易前已支付 39999.99 元）' in formula

def test_row_facts_and_explanation_are_projected_for_display():
    """逐行目录事实与中文解释进入公开载荷；缺省不补、原值透传。"""
    raw = _run(_drug_item(), _drug_entry(sflb="有自付", self_pay_ratio=Decimal('0.1'), a_ypbs=True, a_mzxj=Decimal('80'))).explanations[0]
    assert raw.a_ypbs == "是"
    assert raw.a_mzxj == "80"
    assert raw.a_zyxj is None
    ineligible = project_item_explanation(raw)
    assert ineligible.explanation == ineligible.explanation_reason

    sample = FeeItemExplanation(line_id="L1", classification_label="乙类西药",
        formulas=["单价 300.0000 元×数量 20.00＝6000.000000 元；原单费用 6000.0000 元，两者一致。",
                  "自付二＝取整（费用金额 6000.0000 元×采用自付比例 0.0000）＝0.00 元",
                  "医保内金额＝费用金额 6000.0000 元－医保外金额 0.00 元＝6000.0000 元"],
        notes=["比例来源：本行未维护正值结算时比例，采用本次命中目录的对应比例。"])
    text = _item_explanation(sample)
    assert text is not None and text.startswith("乙类西药；比例来源")
    assert "自付二＝取整" in text and "医保内金额＝" in text
    assert "单价 300.0000" not in text

    material = _run(_material_item(unit_price=Decimal('1000'), fee=Decimal('1000')), _material_entry()).explanations[0]
    assert material.a_ypbs is None
    assert material.settlement_price_limit is None


def test_material_row_uses_catalog_level_as_directory_attribute():
    """耗材与诊疗同一目录表：sfxmdj 作为目录属性，与药品收费类别同义。"""
    raw = _run(_material_item(unit_price=Decimal('1000'), fee=Decimal('1000')),
               _material_entry(sfxmdj='3')).explanations[0]
    assert (raw.classification_code, raw.classification_label) == ('3', '全自付')
    assert raw.classification_source == '诊疗/服务设施目录'
    without = _run(_material_item(unit_price=Decimal('1000'), fee=Decimal('1000')), _material_entry()).explanations[0]
    assert without.classification_label is None
