"""费用分解解释出口单元测试（评审问题 1/3/4 整改后的公开行为）。

费用分解解释按 FEE_EXPLANATION_MODE 生成：
- structured（默认）：结构化 JSON 交模型写完整正文，金额白名单 + 字段归因校验；
- adjust：历史配置别名，与 structured 共用提示词、结构化资料与事实校验；
- deterministic：只输出确定性正文（测试默认）；
- 任一模式下模型未配置/超时/输出不合规都回落确定性正文，事实块不变；
- 证据回答状态（evidence_answer_status）取代 used_model 作为可交付判断。
"""
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.runtime.policy_qa.fee_decomposition.explanation_evidence import (
    ExplanationEvidence, RuleCandidate, RuleChoiceGroup)
from src.runtime.policy_qa.fee_decomposition.fee_items import (
    FeeItemDecision, FeeItemExplanation)
from src.runtime.policy_qa.fee_decomposition.model_explanation import (
    build_model_input, explain_decomposition, selected_ratio_policy_evidence)
from src.runtime.policy_qa.fee_decomposition.public_view import to_public_contract_dict
from src.runtime.policy_qa.fee_decomposition.result import (
    AnswerConstraints, CalculationOperandModel, CalculationRecordModel, CoverageSummary,
    DecompositionProfile, FieldExplanationModel, SettlementDecompositionResult,
    UncertaintyModel)
from src.runtime.policy_qa.public_contract import FeeDecompositionPublic


def public_fee():
    return FeeDecompositionPublic.model_validate(dict(schema_version='1.5', algorithm_version='employee_outpatient_v1', execution_status='partial', reconciliation_status='not_verifiable',
        summary_text='旧模板不应传入模型', fields=[dict(field_code=code, label=label, observed_amount=value, calculated_amount=value, check_type='independent_recalculation', check_status='matched', explanation_level='amount_reconciled', explainable=allowed) for code, label, value, allowed in [('T_FeeAll', '总费用', '100.00', True), ('T_FirstPay', '本次起付', '20.00', True), ('unknown', '未提供计算的项目', '30.00', False)]],
        fee_items=[dict(line_id='1', explainable=True, item_name='测试药品', total_fee='100', classification_label='乙类', centralized_procurement=True, self_pay_ratio='.1', ratio_basis='本行费用金额', decision_path=[dict(code='price', label='单价≤限价', operator='le', actual='100', expected='50', outcome='false')])]))


def _no_model_calls(monkeypatch):
    """登记模型调用次数；返回的替身文本永远是错误内容，用来证明它进不了正文。"""
    calls = []

    def generate(self, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content='1597.50元是现金支付')

    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate', generate)
    return calls


def test_polish_replaces_stiff_block_with_natural_explanation(monkeypatch):
    """润色成功时用自然解释交付；金额/比例必须来自事实块，且不再展示来源/取整/跨院声明。"""
    monkeypatch.setenv('FEE_EXPLANATION_MODE', 'adjust')
    prose = ('这笔大额支付按医保内费用 3195.00 元的 50% 计算，并受年度剩余额度限制，'
             '本次形成 1597.50 元；个人仍需承担剩余部分。')
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *args, **kwargs: SimpleNamespace(content=prose))
    result = explain_decomposition(_public_0408(), '大额支付金额是怎么算的')
    assert result.used_model is True
    assert result.answer == prose
    assert '核对依据：' not in result.answer
    assert '依据：' not in result.answer
    assert '取整' not in result.answer
    assert '跨院' not in result.answer


def test_adjust_rejects_unknown_numbers_false_equations_and_missing_target(monkeypatch):
    """旧 adjust 配置同样检查事实；正确算式不再因展示模式而被拒。"""
    monkeypatch.setenv('FEE_EXPLANATION_MODE', 'deterministic')
    baseline = explain_decomposition(_public_special_567(), '为什么统筹基金支付是4277？')
    monkeypatch.setenv('FEE_EXPLANATION_MODE', 'adjust')
    for junk in ('本次支付 9999 元。', '统筹基金支付＝4277.00＋4277.00 元。', '按取整规则处理后再支付。',
                 '交易前累计跨院未核实，暂按本单口径。'):
        monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                            lambda *args, _junk=junk, **kwargs: SimpleNamespace(content=_junk))
        result = explain_decomposition(_public_special_567(), '为什么统筹基金支付是4277？')
        assert result.used_model is False
        assert result.answer == baseline.answer


def test_polish_model_failure_keeps_deterministic_answer(monkeypatch):
    monkeypatch.setenv('FEE_EXPLANATION_MODE', 'deterministic')
    baseline = explain_decomposition(_public_special_567(), '为什么统筹基金支付是4277？')
    monkeypatch.setenv('FEE_EXPLANATION_MODE', 'adjust')
    def fail(*args, **kwargs):
        raise RuntimeError('provider down')
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate', fail)
    result = explain_decomposition(_public_special_567(), '为什么统筹基金支付是4277？')
    assert result.used_model is False
    assert result.answer == baseline.answer


def test_structured_mode_sends_json_and_returns_model_answer(monkeypatch):
    """固定模式：结构化 JSON 交模型写完整正文，金额/字段归属仍做校验。"""
    monkeypatch.setenv('FEE_EXPLANATION_MODE', 'structured')
    captured = {}
    answer = '本次统筹基金支付 4277.00 元，按 15% 基础比例和 60% 退休折算计算。'
    def generate(self, **kwargs):
        captured['payload'] = json.loads(kwargs['messages'][1].content)
        captured['system'] = kwargs['messages'][0].content
        return SimpleNamespace(content=answer)
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate', generate)
    result = explain_decomposition(_public_special_567(), '为什么统筹基金支付是4277？')
    assert result.used_model is True
    assert result.answer == answer
    assert captured['payload']['question'] == '为什么统筹基金支付是4277？'
    assert captured['payload']['target_evidence']
    assert '回答范围' in captured['system']


def test_structured_mode_rejects_wrong_field_amount(monkeypatch):
    """固定模式同样拦截字段错绑：现金支付说成 4277 即回退确定性正文。"""
    monkeypatch.setenv('FEE_EXPLANATION_MODE', 'deterministic')
    baseline = explain_decomposition(_public_special_567(), '为什么统筹基金支付是4277？')
    monkeypatch.setenv('FEE_EXPLANATION_MODE', 'structured')
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *args, **kwargs: SimpleNamespace(content='现金支付 4277.00 元。'))
    result = explain_decomposition(_public_special_567(), '为什么统筹基金支付是4277？')
    assert result.used_model is False
    assert result.answer == baseline.answer


def test_answer_hides_sources_rounding_and_accumulation_caveats():
    """产品口径：正文/尚待核实不展示来源、取整规则、跨院累计、候选口径待签核。"""
    answer = explain_decomposition(_public_0408(), '大额支付金额是怎么算的').answer
    assert '依据：' not in answer
    assert '取整规则' not in answer
    assert '跨院' not in answer
    assert '据业务签核' not in answer
    from src.runtime.policy_qa.fee_decomposition.result import UncertaintyModel
    public = _public_0408().model_copy(update={"uncertainties": [
        UncertaintyModel(id='u.sp', code='SP_SCALE_CANDIDATE',
                         message='材料按结算事实限价（SP_SCALE）拆分（限内纳入、超限自担）属实证候选口径，待签核。',
                         affected_fields=['T_BigPay'])]})
    result = explain_decomposition(public, '大额支付金额是怎么算的')
    assert 'SP_SCALE' not in result.answer
    assert not any('待签核' in item for item in result.uncertainties)


def test_answer_groups_evidence_into_reading_sections():
    """A 类可读性：金额先行，再按“说明/金额构成/适用比例/依据”分段，不再平铺“采用「」”。"""
    answer = explain_decomposition(_public_special_567(), '为什么统筹基金支付是4277？').answer
    line = next(line for line in answer.splitlines() if '统筹基金支付' in line)
    assert '金额构成：' in line and '适用比例：' in line
    assert '采用「' not in line
    assert line.index('金额构成：') < line.index('适用比例：')
    # 金额仍紧跟字段名：验收判定的字段绑定口径不变
    assert '统筹基金支付 4277.00 元' in line


def test_answer_is_rendered_from_backend_evidence_without_calling_model(monkeypatch):
    """任务 1：费用分解正文由后端证据渲染，不调用自由文本正文生成。"""
    calls = _no_model_calls(monkeypatch)
    result = explain_decomposition(public_fee(), '为什么这样支付？')
    assert calls == []
    assert result.used_model is False
    assert result.evidence_answer_status == 'rendered'
    # 旧模板文案不进入正文；正文逐字段列示真实金额
    assert '旧模板不应传入模型' not in result.answer
    assert '总费用 100.00 元' in result.answer
    assert '本次起付 20.00 元' in result.answer


def test_model_failure_does_not_change_the_trusted_fact_block(monkeypatch):
    """模型抛错不影响输出：与无模型时逐字一致，且不泄露 provider 细节。"""
    baseline = explain_decomposition(public_fee(), '解释费用')

    def fail(*args, **kwargs):
        raise RuntimeError('private transport detail')

    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate', fail)
    result = explain_decomposition(public_fee(), '解释费用')
    assert result.used_model is False
    assert result.answer == baseline.answer
    assert 'private' not in result.answer


def test_unexplained_fields_are_limitations_not_algorithm_causes():
    payload = build_model_input(public_fee(), '解释费用')
    assert payload.unexplained_fields == ['未提供计算的项目']
    assert all(field.explainable for field in payload.decomposition.fields)


def _public_with_selected_rates():
    return FeeDecompositionPublic.model_validate({
        **public_fee().model_dump(),
        'rule_choices': [{
            'group_id': 'rules-rate',
            'title': '大额基金支付比例',
            'field_refs': ['T_FirstPay'],
            'candidates': [{
                'rule_id': 'EOP-RATE-106',
                'name': '门诊大额支付比例-在职-其他医院',
                'value': '70',
                'unit': '%',
                'version': 'V2010-05-01',
                'source': '京人社医发〔2010〕100号第三条',
                'confirmation_status': '官方已核实',
                'status': 'selected',
                'reason': '本单条件符合',
                'checks': [],
            }, {
                'rule_id': 'EOP-RATE-105',
                'name': '门诊大额支付比例-在职-社区',
                'value': '90',
                'unit': '%',
                'version': 'V2010-05-01',
                'source': '另一条比例来源',
                'confirmation_status': '官方已核实',
                'status': 'eligible',
                'reason': '本单机构不符合',
                'checks': [],
            }],
        }],
    })


def test_model_junk_percentage_never_enters_the_answer(monkeypatch):
    """替身返回资料外比例（73%）：正文仍是确定性事实块，73% 不出现。"""
    monkeypatch.setattr(
        'src.model_service.gateway.ModelGateway.generate',
        lambda *args, **kwargs: SimpleNamespace(content='本单待遇比例为73%。'),
    )
    result = explain_decomposition(_public_with_selected_rates(), '为什么是这个比例？')
    assert result.used_model is False
    assert '73%' not in result.answer
    assert '总费用 100.00 元' in result.answer


def test_policy_source_list_only_includes_selected_payment_ratio_and_content():
    from src.runtime.policy_qa.fee_decomposition.model_explanation import selected_ratio_policy_evidence
    public = _public_with_selected_rates()

    evidence = selected_ratio_policy_evidence(public)

    assert len(evidence) == 1
    assert evidence[0][0] == '京人社医发〔2010〕100号第三条'
    assert '70%' in evidence[0][1]
    assert '在职' in evidence[0][1]
    assert '本次采用' in evidence[0][1]


def test_model_auth_error_cannot_leak_into_answer(monkeypatch):
    """模型鉴权错误不改变事实块，provider 细节不泄露。"""
    from src.model_service.exceptions import ModelAuthError

    def fail(*args, **kwargs):
        raise ModelAuthError('secret provider response', model_name='test-model')

    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate', fail)
    result = explain_decomposition(public_fee(), '为什么是这个比例？')
    assert result.used_model is False
    assert 'secret provider response' not in result.answer
    assert '总费用 100.00 元' in result.answer


def test_invented_amount_never_enters_the_answer(monkeypatch):
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *args, **kwargs: SimpleNamespace(content='基金支付987654.32元。'))
    result = explain_decomposition(public_fee(), '解释费用')
    assert result.used_model is False
    assert '987654' not in result.answer
    assert '总费用 100.00 元' in result.answer


def _public_with_payment_gap():
    """已知渠道为零但仍有44.30差额时，保留差额而不猜其归属。"""
    return FeeDecompositionPublic.model_validate(dict(
        schema_version='1.6', algorithm_version='employee_outpatient_v1', execution_status='complete',
        reconciliation_status='mismatched',
        fields=[
            dict(field_code=code, label=label, observed_amount=value, calculated_amount=value,
                 check_type='independent_recalculation', check_status='matched',
                 explanation_level='amount_reconciled', explainable=True)
            for code, label, value in [('T_FeeIn', '医保内费用', '221.50'), ('T_FeeOut', '医保外费用', '28.50'),
                                       ('T_FirstPay', '本次起付承担', '0.00'), ('T_BigPay', '大额支付', '155.05'),
                                       ('T_BigSelfPay', '大额个人自付', '66.45'), ('T_BCPay', '退休补充保险补助', '0.00'),
                                       ('T_JCPay', '军残支付', '0.00'), ('T_OfficalPay', '公疗补充支付', '0.00'),
                                       ('T_SelfPay2', '自付二', '8.50'), ('T_FundPay', '基金合计', '199.35'),
                                       ('T_SelfPayAll', '最终个人承担', '50.65')]
        ] + [
            dict(field_code=code, label=label, observed_amount='0.00', check_type='independent_recalculation',
                 check_status='not_verifiable', explanation_level='observed_only', explainable=False)
            for code, label in [('RETIRE_OFFICER_PAY', '退役医疗费支付'), ('T_BigillPay', '大病保险支付'), ('NT_CivilPay', '民政救助支付')]
        ] + [
            dict(field_code='T_SelfPay1', label='自付一', observed_amount='66.45', check_type='identity_check',
                 check_status='matched', explanation_level='amount_reconciled', explainable=False),
        ],
        fee_items=[
            dict(line_id='1', explainable=True, item_name='注射用培美曲塞二钠', total_fee='60.0000',
                 observed_self_pay_2='6.00', self_pay_ratio='0.1000', division_method='ratio',
                 centralized_procurement=True, unit_price_limit='809.0000', ratio_source='明细结算时比例（正值优先）'),
            dict(line_id='2', explainable=True, item_name='罗沙司他胶囊', total_fee='25.0000',
                 observed_self_pay_2='2.50', self_pay_ratio='0.1000', division_method='ratio'),
            dict(line_id='3', explainable=True, item_name='小换药', total_fee='20.0000',
                 observed_self_pay_2='0.00', division_method='full_out'),
            dict(line_id='4', explainable=True, item_name='复方丹参滴丸', total_fee='20.0000',
                 observed_self_pay_2='0.00', division_method='full_in'),
        ]))


def test_payment_reconciliation_names_gap_without_guessing_a_subsidy():
    payload = build_model_input(_public_with_payment_gap(), '个人支付为什么是50.65元？')
    recon = payload.payment_reconciliation
    assert recon.book_fund_total == '199.35'
    assert recon.itemized_fund_total == '155.05'
    assert recon.fund_gap == '44.30'
    assert recon.book_personal_total == '50.65'
    assert recon.identity_personal_total == '94.95'
    assert recon.personal_gap == '44.30'
    assert '不得归为任何补助' in (recon.note or '')


def test_observed_retire_payment_closes_composition_without_its_own_policy_formula():
    from src.runtime.policy_qa.fee_decomposition.settlement_facts import SettlementFactsView

    public = _public_with_payment_gap()
    public.settlement_facts = SettlementFactsView(chain='outpatient', retire_officer_flag='1')
    public.fields = [field.model_copy(update={'observed_amount': '44.30'})
                     if field.field_code == 'RETIRE_OFFICER_PAY' else field for field in public.fields]
    payload = build_model_input(public, '个人支付为什么是50.65元？')
    recon = payload.payment_reconciliation
    assert recon.itemized_fund_total == '199.35'
    assert recon.fund_gap == '0.00'
    assert recon.identity_personal_total == '50.65'
    assert recon.personal_gap == '0.00'
    assert ('退役医疗费支付', '-44.30') in [(line.label, line.amount) for line in recon.personal_components]
    assert '按原单记录' in (recon.note or '')
    assert payload.decomposition.settlement_facts.retire_officer_flag == '1'
    assert not any(field.field_code == 'RETIRE_OFFICER_PAY' for field in payload.decomposition.fields)


def test_missing_retire_payment_does_not_become_zero_or_a_false_gap():
    public = _public_with_payment_gap()
    public.fields = [field for field in public.fields if field.field_code != 'RETIRE_OFFICER_PAY']
    recon = build_model_input(public, '解释个人支付').payment_reconciliation
    assert recon.fund_gap is None
    assert recon.identity_personal_total is None
    assert recon.personal_gap is None
    assert '退役医疗费支付' in (recon.note or '')
    assert '不按零处理' in (recon.note or '')


def test_self_pay_2_breakdown_lists_contribution_and_excludes_full_self_pay():
    payload = build_model_input(_public_with_payment_gap(), '自付二为什么这么多？')
    breakdown = payload.self_pay_2_breakdown
    assert [(line.item_name, line.basis, line.ratio, line.amount) for line in breakdown.lines] == [
        ('注射用培美曲塞二钠', '60.00', '10%', '6.00'),
        ('罗沙司他胶囊', '25.00', '10%', '2.50'),
    ]
    assert [line.label for line in breakdown.full_out_items] == ['小换药']
    assert breakdown.zero_item_count == 1
    assert '全自费' in (breakdown.note or '')


def test_no_model_prompt_is_built_for_any_fee_question_kind(monkeypatch):
    """任何费用分解问法（整单/字段/行/全覆盖/对比）都不调用自由文本正文生成。"""
    calls = _no_model_calls(monkeypatch)
    public = _public_with_payment_gap()
    for question in ('解释这笔结算', '自付二为什么这么多', '第1行是什么', '请解释全部费用',
                     '医保内费用和医保外费用有什么区别'):
        explain_decomposition(public, question)
    assert calls == []


def _public_special_567():
    """职工门特 567 形态：统筹 4277 由「15%×60%」推出，另有未采用的大病/救助档。"""
    def calc(cid, fid, formula, result):
        return dict(calculation_id=cid, formula_id=fid, formula_version='v1', formula=formula,
                    display_name=cid, layout='generic', operands=[], unrounded_result=None,
                    rounding_rule=None, result=result, explainable=True)

    def field(code, label, value, refs, explainable=True):
        return dict(field_code=code, label=label, observed_amount=value, calculated_amount=value,
                    check_type='independent_recalculation', check_status='matched',
                    explanation_level='causally_explained', explainable=explainable,
                    calculation_refs=refs, source_refs=['S1'])

    return FeeDecompositionPublic.model_validate(dict(
        schema_version='1.6', algorithm_version='employee_outpatient_special_v1',
        execution_status='partial', reconciliation_status='not_verifiable',
        fields=[
            field('T_FeeIn', '医保内费用', '6000.00', ['calc.total_in_scope']),
            field('T_FirstPay', '本次起付承担', '1300.00', ['calc.deductible.split']),
            field('TCZHF', '统筹基金支付', '4277.00', ['calc.deductible.copay_base', 'calc.pool.segment.self_ratio', 'calc.pool.segmented']),
            field('TCZIF', '统筹自付', '423.00', ['calc.pool.self_pay']),
            field('JCZHF', '军残补助', '1511.50', [], explainable=False),
            field('T_BigillPay', '大病保险支付', '0.00', [], explainable=False),
            field('CIVIL_IN', '医疗救助支付', '0.00', [], explainable=False),
            field('T_CashPay', '现金支付', '9.24', [], explainable=False),
            field('T_PersonCountPay', '账户支付', '0.00', [], explainable=False),
        ],
        calculations=[
            calc('calc.total_in_scope', 'catalog_total_in_scope_v1', '医保内费用合计＝6000.00 元', '6000.00'),
            calc('calc.deductible.split', 'deductible_split_v1', '门特起付线拆分＝较小值（6000.0000，1300）＝1300.00 元', '1300.00'),
            calc('calc.deductible.copay_base', 'copay_base_v1', '报销基数（扣减后）＝6000.0000－1300.00＝4700.0000 元', '4700.0000'),
            calc('calc.pool.segment.self_ratio', 'x', '本段实际自付比例＝0.15×0.6＝0.090', '0.090'),
            calc('calc.pool.segmented', 'x', '统筹基金分段支付＝取整（4700.0000×（1－0.090））＝4277.00 元', '4277.00'),
            calc('calc.pool.self_pay', 'x', '统筹自付＝4700.0000－4277.00＝423.00 元', '423.00'),
        ],
        rule_choices=[
            dict(group_id='rules-ESP-RATE', title='统筹分段 · 在职自付基础比例', calculation_refs=['calc.pool.segment.self_ratio'],
                 input_refs=[], field_refs=['TCZHF'], candidates=[dict(
                     rule_id='ESP-RATE-101', name='统筹分段-三级-起付至1万段-在职', value='15', unit='%', version='2024-04-30',
                     effective_from='2024-04-30', effective_to=None, source='ESP-RATE 参数表',
                     confirmation_status='文档明确-待官方核证', status='selected', reason='',
                     checks=[dict(name='比例基础档', actual='在职', expected='在职', outcome='met', input_ref=None)])]),
            dict(group_id='rules-ESP-RATE-factor', title='退休自付折算系数', calculation_refs=['calc.pool.segmented'],
                 input_refs=[], field_refs=['TCZHF'], candidates=[dict(
                     rule_id='ESP-RATE-113', name='退休人员个人支付比例折算规则', value='60', unit='%', version='2024-04-30',
                     effective_from=None, effective_to=None, source='ESP-RATE 参数表',
                     confirmation_status='文档明确-待官方核证', status='selected', reason='',
                     checks=[dict(name='人员身份', actual='退休', expected='退休', outcome='met', input_ref=None)])]),
            dict(group_id='rules-secondary-db', title='二次大病保险比例', calculation_refs=[], input_refs=[], field_refs=['T_BigillPay'],
                 candidates=[dict(rule_id='SDB-1', name='救助对象 · 第1段', value='65.00', unit='%', version='v1',
                                  effective_from=None, effective_to=None, source='政策', confirmation_status='候选口径',
                                  status='selected', reason='', checks=[])]),
            dict(group_id='rules-secondary-aid', title='医疗救助比例', calculation_refs=[], input_refs=[], field_refs=['CIVIL_IN'],
                 candidates=[dict(rule_id='MAF-1', name='救助身份 · 85%', value='85.00', unit='%', version='v1',
                                  effective_from=None, effective_to=None, source='政策', confirmation_status='候选口径',
                                  status='selected', reason='', checks=[])]),
        ],
        fee_items=[], uncertainties=[], sources=[], path_steps=[], formula_inputs=[],
    ))


def test_target_field_limits_payload_and_renders_its_own_evidence():
    """Issue #83 第 3 项：问统筹就只给统筹的证据，并先给出后端渲染的事实。"""
    public = _public_special_567()
    payload = build_model_input(public, '为什么统筹基金支付是4277？')
    codes = [field.field_code for field in payload.decomposition.fields]
    assert codes == ['TCZHF']
    assert {calc.calculation_id for calc in payload.decomposition.calculations} == {
        'calc.deductible.copay_base', 'calc.pool.segment.self_ratio', 'calc.pool.segmented'}
    assert {group.group_id for group in payload.decomposition.rule_choices} == {'rules-ESP-RATE', 'rules-ESP-RATE-factor'}
    evidence = payload.target_evidence
    assert [item.field_code for item in evidence] == ['TCZHF']
    assert evidence[0].amount == '4277.00'
    # 公式展示可压缩冗余尾零（4277.00 → 4277），数值必须相等
    formula = evidence[0].formula or ''
    assert Decimal(formula.rsplit('＝', 1)[1].replace('元', '').strip()) == Decimal('4277.00')
    assert [ratio.chosen for ratio in evidence[0].ratios] == [
        '统筹分段-三级-起付至1万段-在职 15%', '退休人员个人支付比例折算规则 60%']
    assert evidence[0].sentence and '4277.00 元' in evidence[0].sentence


def test_citations_follow_target_field_not_title_keyword():
    """Issue #83 第 3 项：引用围绕目标字段，不给大病/救助，给退休折算。"""
    public = _public_special_567()
    citations = selected_ratio_policy_evidence(public, ['TCZHF'])
    joined = "；".join(excerpt for _, excerpt in citations)
    assert '退休人员个人支付比例折算规则 60%' in joined
    assert '统筹分段-三级-起付至1万段-在职 15%' in joined
    assert '大病' not in joined and '救助' not in joined


def test_fund_channels_include_pooling_and_personal_components_include_pool_self_pay():
    """Issue #83 第 2 项：门特基金渠道含统筹，个人构成含统筹自付，不再出现 -423 的假矛盾。"""
    recon = build_model_input(_public_special_567(), '解释个人支付').payment_reconciliation
    labels = [line.label for line in recon.fund_channels]
    assert '统筹基金支付' in labels
    assert '统筹自付' in [line.label for line in recon.personal_components]


@pytest.mark.parametrize("junk", [
    '现金支付4277.00元。',
    '现金支付：4277.00元。',
    '本单现金支付共计4277.00元。',
    '| 项目 | 金额 |\n| --- | --- |\n| 现金支付 | 4277.00 |',
    '**现金支付 4277.00 元**',
])
def test_wrong_field_attribution_from_model_never_enters_answer(monkeypatch, junk):
    """错误归属的自由文本（把统筹 4277 说成现金）一律进不了确定性正文。"""
    calls = []
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *args, **kwargs: calls.append(1) or SimpleNamespace(content=junk))
    result = explain_decomposition(_public_special_567(), '为什么统筹基金支付是4277？')
    assert calls == []
    assert result.used_model is False
    assert result.evidence_answer_status == 'rendered'
    assert '4277.00' in result.answer
    assert '统筹基金支付' in result.answer
    # 现金支付本单是 9.24：不得出现把 4277 归到现金的表述
    assert '现金支付4277' not in result.answer.replace(' ', '').replace('：', '').replace('**', '')


def test_target_field_answer_carries_formula_and_adopted_ratios(monkeypatch):
    """命中字段的正文核验实际构成：金额 + 真实算式 + 采用档，且不调模型。"""
    calls = _no_model_calls(monkeypatch)
    result = explain_decomposition(_public_special_567(), '为什么统筹基金支付是4277？')
    assert calls == []
    assert '统筹基金支付 4277.00 元' in result.answer
    assert '4277.00' in result.answer
    assert '15%' in result.answer and '60%' in result.answer


def test_multi_field_question_keeps_both_targets_and_line_items(monkeypatch):
    """一句问两个字段时都保留；总额/个人支付必须带明细与上游计算。"""
    public = FeeDecompositionPublic.model_validate(dict(
        schema_version='1.6', algorithm_version='resident_outpatient_v1', execution_status='complete',
        reconciliation_status='matched',
        fields=[
            dict(field_code='T_FeeAll', label='总费用', observed_amount='100.00', calculated_amount='100.00',
                 check_type='detail_aggregation', check_status='matched', explanation_level='amount_reconciled',
                 explainable=True, calculation_refs=['calc.catalog.total_fee']),
            dict(field_code='T_SelfPayAll', label='最终个人承担', observed_amount='40.00', calculated_amount='40.00',
                 check_type='independent_recalculation', check_status='matched',
                 explanation_level='causally_explained', explainable=True,
                 calculation_refs=['calc.self_pay_all.parts']),
        ],
        calculations=[
            dict(calculation_id='calc.catalog.total_fee', formula='总费用＝明细合计 100.00 元',
                 display_name='总费用合计', formula_id='catalog_total_fee_v1', formula_version='v1',
                 layout='generic', operands=[dict(display_name='明细费用', value='100.00', input_ref='input-fee')],
                 result='100.00', explainable=True),
            dict(calculation_id='calc.catalog.total_out_scope', formula='医保外费用合计＝40.00 元',
                 display_name='医保外费用合计', formula_id='catalog_total_out_scope_v1', formula_version='v1',
                 layout='generic', operands=[], result='40.00', explainable=True),
            dict(calculation_id='calc.self_pay_all.parts', formula='最终个人承担＝医保外 40.00 元',
                 display_name='最终个人承担', formula_id='self_pay_all_components_v1', formula_version='v1',
                 layout='sum', operands=[dict(display_name='医保外费用', value='40.00',
                                              calculation_ref='calc.catalog.total_out_scope')],
                 result='40.00', explainable=True),
        ],
        fee_items=[dict(line_id='1', item_name='药品A', total_fee='60.00', observed_out_scope='40.00',
                        status='calculated', division_method='ratio', explainable=True)],
    ))
    calls = _no_model_calls(monkeypatch)
    from src.runtime.policy_qa.fee_decomposition.model_explanation import resolve_target_fields
    question = '费用总金额为什么这么多，个人支付总金额为什么这么多'
    assert set(resolve_target_fields(public, question)) == {'T_FeeAll', 'T_SelfPayAll'}
    payload = build_model_input(public, question)
    assert {field.field_code for field in payload.decomposition.fields} == {'T_FeeAll', 'T_SelfPayAll'}
    assert len(payload.decomposition.fee_items) == 1
    calc_ids = {calc.calculation_id for calc in payload.decomposition.calculations}
    # 上游依赖闭包（个人支付分量引用医保外合计）
    assert {'calc.self_pay_all.parts', 'calc.catalog.total_out_scope', 'calc.catalog.total_fee'} <= calc_ids
    result = explain_decomposition(public, question)
    assert calls == []
    assert '总费用 100.00 元' in result.answer
    assert '最终个人承担 40.00 元' in result.answer


def _public_with_items_and_total():
    """居民门诊形态：字段医保内 3195，明细含一行医保内 440。"""
    return FeeDecompositionPublic.model_validate(dict(
        schema_version='1.6', algorithm_version='resident_outpatient_v1', execution_status='complete',
        reconciliation_status='matched',
        fields=[
            dict(field_code='T_FeeIn', label='医保内费用', observed_amount='3195.00',
                 calculated_amount='3195.00', check_type='independent_recalculation',
                 check_status='matched', explanation_level='causally_explained', explainable=True),
            dict(field_code='T_FeeOut', label='医保外费用', observed_amount='240.00',
                 calculated_amount='240.00', check_type='independent_recalculation',
                 check_status='matched', explanation_level='causally_explained', explainable=True),
        ],
        fee_items=[
            dict(line_id='1', item_name='复方丹参滴丸', total_fee='440.00',
                 observed_in_scope='440.00', observed_out_scope='0.00', observed_self_pay_2='0.00',
                 status='calculated', division_method='full_in', explainable=True),
            dict(line_id='2', item_name='小换药', total_fee='60.00',
                 observed_in_scope='0.00', observed_out_scope='60.00', observed_self_pay_2='0.00',
                 status='calculated', division_method='full_out', explainable=True),
        ],
    ))


def test_field_answer_amounts_are_bound_by_construction(monkeypatch):
    """确定性正文里字段金额天然归属正确：医保内 3195、医保外 240，替身文本无效。"""
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *args, **kwargs: SimpleNamespace(content='医保内合计440.00元。'))
    result = explain_decomposition(_public_with_items_and_total(), '医保内为什么这么多')
    assert result.used_model is False
    assert '医保内费用 3195.00 元' in result.answer
    assert '医保内合计440' not in result.answer.replace(' ', '')


def test_cap_room_is_a_citable_calculation(monkeypatch):
    """封顶余额是封顶线−交易前已支付，有自己的计算记录并进入确定性正文。"""
    public = FeeDecompositionPublic.model_validate(dict(
        schema_version='1.6', algorithm_version='resident_outpatient_special_v1',
        execution_status='complete', reconciliation_status='matched',
        fields=[dict(field_code='DEGWYZHF', label='门诊大额基金支付金额', observed_amount='837.83',
                     calculated_amount='837.83', check_type='independent_recalculation',
                     check_status='matched', explanation_level='causally_explained', explainable=True,
                     calculation_refs=['calc.big_pay.capped'])],
        calculations=[
            dict(calculation_id='calc.big_pay.cap_room',
                 formula='年度封顶余额（封顶线−交易前已支付）＝封顶 250000 元－交易前已支付 51981.75 元＝198018.25 元',
                 display_name='年度封顶余额', formula_id='cap_room_v1', formula_version='v1',
                 layout='generic', operands=[], result='198018.25', explainable=True),
            dict(calculation_id='calc.big_pay.capped', formula='大额支付 837.83 元',
                 display_name='居民门特大额支付', formula_id='resident_special_big_pay_clamp_v1',
                 formula_version='v1', layout='generic',
                 operands=[dict(display_name='年度封顶余额', value='198018.25',
                                calculation_ref='calc.big_pay.cap_room')],
                 result='837.83', explainable=True),
        ],
        rule_choices=[dict(group_id='rules-RSP-CAP', title='封顶线 · 不适用',
                           calculation_refs=['calc.big_pay.capped'], input_refs=[], field_refs=[],
                           candidates=[dict(rule_id='RSP-CAP-002', name='居民基金年度最高支付限额（2019 起）',
                                            value='250000', unit='元/保险年度', source='mz.docx 城乡居民住院§封顶线',
                                            version='V2019-01-01', effective_from='2019-01-01',
                                            effective_to='尚未终止', confirmation_status='文档明确',
                                            status='selected', reason='', checks=[])])],
    ))
    calls = _no_model_calls(monkeypatch)
    payload = build_model_input(public, '封顶余额还有多少？')
    assert any(calc.calculation_id == 'calc.big_pay.cap_room' for calc in payload.decomposition.calculations)
    result = explain_decomposition(public, '封顶余额还有多少？')
    assert calls == []
    assert result.evidence_answer_status == 'rendered'
    assert '837.83' in result.answer
    evidence = selected_ratio_policy_evidence(public)
    # 金额型标准（元）也进入依据，并按两位小数展示
    assert any('250000.00元' in text for _, text in evidence)


def test_whole_settlement_without_fields_falls_back_to_explainable_calculations(monkeypatch):
    """整单问法且无字段证据时，用本单已可解释的计算记录兜底。"""
    public = FeeDecompositionPublic.model_validate(dict(
        schema_version='1.6', algorithm_version='resident_outpatient_special_v1',
        execution_status='complete', reconciliation_status='matched',
        fields=[],
        calculations=[dict(calculation_id='calc.big_pay.cap_room',
                           formula='年度封顶余额＝封顶 250000.00－交易前已支付 51981.75＝198018.25 元',
                           display_name='年度封顶余额', formula_id='cap_room_v1', formula_version='v1',
                           layout='generic', operands=[], result='198018.25', explainable=True)],
    ))
    calls = _no_model_calls(monkeypatch)
    result = explain_decomposition(public, '封顶余额还有多少？')
    assert calls == []
    assert result.evidence_answer_status == 'rendered'
    assert '198018.25' in result.answer


def test_unknown_target_field_is_listed_as_gap_not_borrowed_success(monkeypatch):
    """目标字段无证据时逐项列缺口：不吞掉、不借用其他字段的成功、不整题冒充已解释。"""
    public = FeeDecompositionPublic.model_validate(dict(
        schema_version='1.9', algorithm_version='employee_outpatient_v1',
        execution_status='partial', reconciliation_status='not_verifiable',
        fields=[dict(field_code='T_BigPay', label='当次门诊大额基金支付金额',
                     observed_amount='420.00', calculated_amount=None,
                     check_type='independent_recalculation', check_status='not_verifiable',
                     explanation_level='observed_only', explainable=False)],
        uncertainties=[dict(id='u.big_pay.base', code='UPSTREAM_BASE_MISSING',
                            message='起付线分解未得出共付段基数，大额支付阻断。',
                            affected_fields=['T_BigPay'])],
    ))
    calls = _no_model_calls(monkeypatch)
    result = explain_decomposition(public, '大额支付420元和70%怎么算？')
    assert calls == []
    assert '420.00' in result.answer
    assert '共付段基数' in result.answer
    assert '大额支付阻断' in result.answer
    assert '70%' not in result.answer


def test_missing_target_gets_explicit_gap_line(monkeypatch):
    """被点名的模板展示字段未绑定计算且无固定说明：如实声明缺口，不借用其他字段的成功。"""
    from src.runtime.policy_qa.fee_decomposition.settlement_facts import (
        SettlementDisplayField, SettlementDisplayView, SettlementFactsView)
    public = public_fee()
    public.settlement_facts = SettlementFactsView(
        chain='outpatient',
        display_template=SettlementDisplayView(
            template_id='employee_outpatient', version='1.0', title='测试模板',
            layout_status='provisional',
            fields=[SettlementDisplayField(
                key='beyond_cap', label='大额超封顶金额', section='transaction',
                row=1, column=1, scope='patient_actual', value=None,
                source_kind='unmapped', status='unmapped', field_code=None)]))
    calls = _no_model_calls(monkeypatch)
    result = explain_decomposition(public, '大额超封顶金额是多少？')
    assert calls == []
    # 模板字段进入同一份目标证据：列示名称并如实声明无独立计算/归属映射，缺值不补零
    assert '大额超封顶金额' in result.answer
    assert '无独立计算或费用归属映射' in result.answer


def test_no_evidence_at_all_keeps_unavailable(monkeypatch):
    """完全没有可交付依据时维持不可用（不拿空壳文案充数）。"""
    public = FeeDecompositionPublic.model_validate(dict(
        schema_version='1.5', algorithm_version='employee_outpatient_v1',
        execution_status='unavailable', reconciliation_status='not_verifiable',
        summary_text='', fields=[], fee_items=[]))
    calls = _no_model_calls(monkeypatch)
    result = explain_decomposition(public, '解释费用')
    assert calls == []
    assert result.used_model is False
    assert result.evidence_answer_status == 'none'
    assert '仍可查看' in result.answer
    assert result.uncertainties


def test_cover_all_answer_keeps_field_explanations_and_line_evidence(monkeypatch):
    """全覆盖意图（"解释全部费用"）：字段固定说明与逐行证据都交付，不只剩行证据。"""
    calls = _no_model_calls(monkeypatch)
    result = explain_decomposition(public_fee(), '请解释全部费用')
    assert calls == []
    assert result.evidence_answer_status == 'rendered'
    # 字段固定说明（summary 字段）与行证据都在正文里
    assert '总费用 100.00 元' in result.answer
    assert '测试药品' in result.answer


def test_line_evidence_carries_this_line_amounts_and_limit_path():
    """第 6 行证据：1935/1835/100 与本行限价路径；模型输入只保留目标行及其实际依赖。"""
    public = _public_with_duplicate_named_lines()
    payload = build_model_input(public, '第 6 行人工晶体为什么贵')
    evidence = payload.line_evidence
    assert evidence is not None
    assert evidence.display_no == 6 and evidence.line_id == '5'
    assert evidence.total_fee == '1935.0000'
    assert evidence.observed_in_scope == '1835.0000'
    assert evidence.observed_out_scope == '100.0000'
    assert evidence.observed_self_pay_2 == '100.0000'
    assert evidence.limit_source == '明细结算时限价'
    assert '1935.00' in evidence.sentence and '1835.00' in evidence.sentence
    assert '100.00' in evidence.sentence
    # 模型输入收敛：只有目标行、不带整单基金渠道字段与其他明细行
    assert [line.line_id for line in payload.decomposition.fee_items] == ['5']
    assert payload.decomposition.fields == []
    assert {calc.calculation_id for calc in payload.decomposition.calculations} == {
        'calc.catalog.material_price_limit.5'}
    assert payload.actual_payment_shares == []
    assert payload.payment_reconciliation.book_fund_total is None
    assert payload.self_pay_2_breakdown.lines == []
    # 其他行金额不在模型可见资料里（第 1 行 440、整单医保内 3195 等）
    dumped = payload.model_dump_json()
    assert '440' not in dumped
    assert '3195' not in dumped


# ── 明细行目标解析与单行口径（用户故事：指定某行后识别/取证/校验/回退始终围绕同一行） ──


def _public_with_duplicate_named_lines():
    """居民门诊形态：第 5/6 行同名人工晶体（200.00 与 1935.00，后者限价 1835 拆出 100）。

    对应活库 011100030X240408000002 的 fee_items 结构（.scratch/four-chains-quality
    -2026-10-21/resident-outpatient.json），display 序号 = 列表 index+1。
    """
    def item(line_id, name, fee, in_scope, out_scope, sp2, **overrides):
        base = dict(line_id=line_id, item_name=name, unit_price=fee, quantity='1.00',
                    total_fee=fee, observed_in_scope=in_scope, observed_out_scope=out_scope,
                    observed_self_pay_2=sp2, status='calculated', explainable=True,
                    division_method='full_in')
        return base | overrides

    return FeeDecompositionPublic.model_validate(dict(
        schema_version='1.6', algorithm_version='resident_outpatient_v1',
        execution_status='complete', reconciliation_status='matched',
        fields=[
            dict(field_code='T_FeeAll', label='费用总金额', observed_amount='3435.00',
                 calculated_amount='3435.00', check_type='detail_aggregation',
                 check_status='matched', explanation_level='amount_reconciled',
                 explainable=True, calculation_refs=['calc.catalog.total_fee']),
            dict(field_code='T_FeeIn', label='医疗保险范围内金额', observed_amount='3195.00',
                 calculated_amount='3195.00', check_type='independent_recalculation',
                 check_status='matched', explanation_level='causally_explained',
                 explainable=True, calculation_refs=['calc.catalog.total_in_scope']),
            dict(field_code='T_FeeOut', label='医疗保险范围外金额', observed_amount='240.00',
                 calculated_amount='240.00', check_type='independent_recalculation',
                 check_status='matched', explanation_level='causally_explained',
                 explainable=True, calculation_refs=['calc.catalog.total_out_scope']),
        ],
        calculations=[
            dict(calculation_id='calc.catalog.material_price_limit.5',
                 formula='医保内金额＝结算时限价 1835.0000 元×数量 1.00＝1835.000000 元',
                 display_name='材料结算时限价拆分', formula_id='material_price_limit_v1',
                 formula_version='v1', layout='generic',
                 operands=[dict(display_name='结算时限价', value='1835.0000', input_ref='input-limit-5'),
                           dict(display_name='数量', value='1.00', input_ref='input-qty-5')],
                 result='1835.000000', explainable=True),
            dict(calculation_id='calc.catalog.total_fee',
                 formula='费用总金额＝明细合计 3435.00 元',
                 display_name='费用总金额合计', formula_id='catalog_total_fee_v1',
                 formula_version='v1', layout='sum', operands=[],
                 result='3435.00', explainable=True),
            dict(calculation_id='calc.catalog.total_in_scope',
                 formula='医保内费用合计＝3195.00 元',
                 display_name='医保内费用合计', formula_id='catalog_total_in_scope_v1',
                 formula_version='v1', layout='sum', operands=[],
                 result='3195.00', explainable=True),
            dict(calculation_id='calc.catalog.total_out_scope',
                 formula='医保外费用合计＝240.00 元',
                 display_name='医保外费用合计', formula_id='catalog_total_out_scope_v1',
                 formula_version='v1', layout='sum', operands=[],
                 result='240.00', explainable=True),
        ],
        sources=[
            dict(ref_id='rule.EOP-MAT-005', category='policy_basis',
                 title='材料限价规则来源', values=['V2021-01-01'],
                 confirmation_status='文档明确-待官方核证'),
        ],
        fee_items=[
            item('0', '复方丹参滴丸', '440.0000', '440.0000', '0.0000', '0.0000'),
            item('1', '注射用培美曲塞二钠', '400.0000', '360.0000', '40.0000', '40.0000',
                 division_method='ratio', self_pay_ratio='0.1000'),
            item('2', '罗沙司他胶囊', '400.0000', '360.0000', '40.0000', '40.0000',
                 division_method='ratio', self_pay_ratio='0.1000'),
            item('3', '小换药', '60.0000', '0.0000', '60.0000', '0.0000',
                 division_method='full_out'),
            item('4', '单焦点散光型白内障人工晶体', '200.0000', '200.0000', '0.0000', '0.0000'),
            item('5', '单焦点散光型白内障人工晶体', '1935.0000', '1835.0000', '100.0000', '100.0000',
                 division_method='limit', unit_price_limit='1835.0000', limit_source='明细结算时限价',
                 calculated_in_scope='1835.00', calculated_out_scope='100.00',
                 calculated_self_pay_2='100.00',
                 calculation_refs=['calc.catalog.material_price_limit.5'],
                 decision_path=[dict(code='material_price_limit',
                                     label='材料单价超结算时限价：限内纳入、超限自担',
                                     operator='gt', actual='1935.0000', expected='1835.0000',
                                     outcome='true', rule_refs=['EOP-MAT-005'],
                                     calculation_refs=['calc.catalog.material_price_limit.5'])],
                 formulas=['医保内金额＝结算时限价 1835.0000 元×数量 1.00＝1835.000000 元',
                           '医保外金额＝费用金额 1935.0000 元－医保内金额 1835.000000 元＝100.000000 元']),
        ]))


def test_line_number_question_locates_display_order_to_line_id():
    """“第 6 行”按展示顺序定位到列表第 6 个元素的 line_id（本例 line_id=5）。"""
    from src.runtime.policy_qa.fee_decomposition.model_explanation import resolve_question_target
    public = _public_with_duplicate_named_lines()
    target = resolve_question_target(public, '第 6 行人工晶体为什么贵')
    assert target.kind == 'fee_line'
    assert target.display_no == 6
    assert target.line_id == '5'


def test_list_marker_style_locates_the_same_line():
    from src.runtime.policy_qa.fee_decomposition.model_explanation import resolve_question_target
    public = _public_with_duplicate_named_lines()
    target = resolve_question_target(public, '6. 人工晶体为什么贵')
    assert target.kind == 'fee_line'
    assert target.display_no == 6
    assert target.line_id == '5'


def test_unique_item_name_locates_line_directly():
    from src.runtime.policy_qa.fee_decomposition.model_explanation import resolve_question_target
    public = _public_with_duplicate_named_lines()
    target = resolve_question_target(public, '罗沙司他胶囊为什么贵')
    assert target.kind == 'fee_line'
    assert target.display_no == 3
    assert target.line_id == '2'


def test_line_question_scopes_to_the_other_duplicate_line():
    """指定第 5 行：只解释 200.00，不带第 6 行限价（1835 不进 payload）。"""
    public = _public_with_duplicate_named_lines()
    payload = build_model_input(public, '第 5 行人工晶体多少钱')
    evidence = payload.line_evidence
    assert evidence is not None
    assert evidence.line_id == '4'
    assert evidence.total_fee == '200.0000'
    assert [line.line_id for line in payload.decomposition.fee_items] == ['4']
    assert '1835' not in payload.model_dump_json()


def test_duplicate_name_only_question_is_ambiguous_without_model_call(monkeypatch):
    """只问重复项目名：ambiguous，提示列两行供选择，不调模型。"""
    from src.runtime.policy_qa.fee_decomposition.model_explanation import resolve_question_target
    public = _public_with_duplicate_named_lines()
    target = resolve_question_target(public, '人工晶体为什么贵')
    assert target.kind == 'ambiguous'
    assert '第 5 行' in target.prompt and '200.00' in target.prompt
    assert '第 6 行' in target.prompt and '1935.00' in target.prompt
    called = []
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *args, **kwargs: called.append(1) or SimpleNamespace(content='x'))
    result = explain_decomposition(public, '人工晶体为什么贵')
    assert called == []
    assert result.used_model is False
    assert result.answer == target.prompt


def test_line_question_with_attributes_stays_off_settlement_totals(monkeypatch):
    """“第 6 行医保内、医保外多少”：回答本行金额，不命中整单合计字段。"""
    from src.runtime.policy_qa.fee_decomposition.model_explanation import resolve_question_target
    public = _public_with_duplicate_named_lines()
    target = resolve_question_target(public, '第 6 行医保内、医保外多少')
    assert target.kind == 'fee_line'
    assert set(target.attributes) == {'observed_in_scope', 'observed_out_scope'}
    payload = build_model_input(public, '第 6 行医保内、医保外多少')
    assert payload.decomposition.fields == []
    calls = _no_model_calls(monkeypatch)
    result = explain_decomposition(public, '第 6 行医保内、医保外多少')
    assert calls == []
    assert '1835.00' in result.answer and '100.00' in result.answer


def test_line_answer_contains_only_target_line_evidence(monkeypatch):
    """单行正文只含目标行内容：其他行金额（440/200/3195）不出现。"""
    public = _public_with_duplicate_named_lines()
    calls = _no_model_calls(monkeypatch)
    result = explain_decomposition(public, '第 6 行人工晶体为什么贵')
    assert calls == []
    assert '1935.00' in result.answer and '1835.00' in result.answer
    assert '复方丹参滴丸' not in result.answer
    assert '罗沙司他' not in result.answer
    assert '440' not in result.answer
    assert '200.00' not in result.answer
    assert '3195' not in result.answer


def _unexplainable_line_public():
    """第 6 行未取得独立计算依据（explainable=false）：只留原单事实。"""
    public = _public_with_duplicate_named_lines()
    public.fee_items = [line.model_copy(update=dict(
        explainable=False, explanation_reason='本行尚未逐项算平，算法待补全',
        calculated_in_scope=None, calculated_out_scope=None, calculated_self_pay_2=None,
        unit_price_limit=None, formulas=[], notes=[], decision_path=[],
        calculation_refs=[], limit_source=None)) if line.line_id == '5' else line
        for line in public.fee_items]
    return public


def test_unexplainable_line_gives_facts_only_without_other_line_formulas(monkeypatch):
    """明细不可解释：只给事实不给原因；正文不输出其他项目公式。"""
    public = _unexplainable_line_public()
    payload = build_model_input(public, '第 6 行人工晶体为什么贵')
    evidence = payload.line_evidence
    assert evidence is not None
    assert evidence.explainable is False
    assert evidence.explanation_reason
    assert evidence.formulas == []
    calls = _no_model_calls(monkeypatch)
    result = explain_decomposition(public, '第 6 行人工晶体为什么贵')
    assert calls == []
    assert '1935.00' in result.answer
    assert evidence.explanation_reason in result.answer
    assert '复方丹参滴丸' not in result.answer
    assert '440' not in result.answer


def test_out_of_range_line_number_is_invalid_without_model_call(monkeypatch):
    """无效行号：定位提示，不退成整单问题，不调模型，不输出其他项目公式。"""
    from src.runtime.policy_qa.fee_decomposition.model_explanation import resolve_question_target
    public = _public_with_duplicate_named_lines()
    target = resolve_question_target(public, '第 9 行是什么')
    assert target.kind == 'invalid'
    assert '共 6 行' in target.prompt
    called = []
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *args, **kwargs: called.append(1) or SimpleNamespace(content='x'))
    result = explain_decomposition(public, '第 9 行是什么')
    assert called == []
    assert result.used_model is False
    assert result.answer == target.prompt
    assert '复方丹参滴丸' not in result.answer


def test_name_mismatch_with_line_number_is_invalid():
    """名称与行号不符：invalid，明确提示该行实际项目，不自动退成整单问题。"""
    from src.runtime.policy_qa.fee_decomposition.model_explanation import resolve_question_target
    public = _public_with_duplicate_named_lines()
    target = resolve_question_target(public, '第 6 行复方丹参滴丸为什么贵')
    assert target.kind == 'invalid'
    assert '单焦点散光型白内障人工晶体' in target.prompt


def test_resolve_target_fields_compat_wrapper_keeps_summary_behavior():
    """兼容包装：summary 问题返回 field_codes；行问题/整单问题返回空。"""
    from src.runtime.policy_qa.fee_decomposition.model_explanation import (
        resolve_question_target, resolve_target_fields)
    public = _public_with_duplicate_named_lines()
    assert resolve_target_fields(public, '第 6 行人工晶体为什么贵') == []
    assert resolve_target_fields(public, '人工晶体为什么贵') == []
    assert resolve_target_fields(public, '解释这笔结算') == []
    assert set(resolve_target_fields(public, '医保内费用为什么这么多')) == {'T_FeeIn'}
    assert resolve_question_target(public, '解释这笔结算').kind == 'whole_settlement'
    summary = resolve_question_target(public, '医保内费用为什么这么多')
    assert summary.kind == 'summary_fields'
    assert summary.field_codes == ['T_FeeIn']


# ── 评审问题 1：四链真实形态的确定性正文（0408 居民门诊走真实投影） ──


def _0408_result() -> SettlementDecompositionResult:
    """0408 居民门诊：大额 1597.50 封顶算式、起付 0（交易前累计 5159≥550）、自付二 180。"""
    def calc(cid, fid, pairs, result):
        return CalculationRecordModel(
            calculation_id=cid, formula_id=fid, formula_version='v1',
            operands=[CalculationOperandModel(ref=ref, value=value) for ref, value in pairs],
            result=result)

    def field(code, label, value, refs, check_type='independent_recalculation'):
        return FieldExplanationModel(
            field_code=code, label=label, check_type=check_type, check_status='matched',
            observed_amount=value, calculated_amount=value, difference='0.00',
            explanation_level='causally_explained', calculation_refs=refs)

    def item(line_id, name, fee, in_scope, out_scope, sp2, **overrides):
        kwargs = dict(
            line_id=line_id, item_name=name, unit_price=fee, quantity='1.00', total_fee=fee,
            observed_in_scope=in_scope, observed_out_scope=out_scope, observed_self_pay_2=sp2,
            calculated_in_scope=in_scope, calculated_out_scope=out_scope,
            calculated_self_pay_2=sp2, status='calculated', verification_status='verified',
            explainable=True, division_method='full_in')
        kwargs.update(overrides)
        return FeeItemExplanation(**kwargs)

    return SettlementDecompositionResult(
        settlement_ref='settlement:0408', algorithm_version='resident_outpatient_v1',
        profile=DecompositionProfile(insurance_type='resident', medical_category='outpatient'),
        execution_status='partial', reconciliation_status='matched',
        fields=[
            field('T_FeeAll', '费用总金额', '3435.00', ['calc.catalog.total_fee'], 'detail_aggregation'),
            field('T_FeeIn', '医疗保险范围内金额', '3195.00', ['calc.catalog.total_in_scope']),
            field('T_FeeOut', '医疗保险范围外金额', '240.00', ['calc.catalog.total_out_scope']),
            field('T_FirstPay', '本次起付承担', '0.00', ['calc.deductible.split']),
            field('T_SelfPay2', '个人支付自付（二）金额', '180.00', ['calc.catalog.total_self_pay_2']),
            field('T_BigPay', '大额支付', '1597.50', ['calc.big_pay.capped']),
            field('T_SelfPayAll', '个人支付总金额', '1837.50', ['calc.self_pay_all.parts']),
            field('T_CashPay', '现金支付', '1837.50', [], 'identity_check'),
            field('T_PersonCountPay', '账户支付', '0.00', [], 'identity_check'),
        ],
        calculations=[
            calc('calc.catalog.total_fee', 'catalog_total_fee_v1', [], '3435.00'),
            calc('calc.catalog.total_in_scope', 'catalog_total_in_scope_v1', [], '3195.00'),
            calc('calc.catalog.total_out_scope', 'catalog_total_out_scope_v1', [], '240.00'),
            calc('calc.catalog.total_self_pay_2', 'catalog_total_self_pay_2_v1', [], '180.00'),
            calc('calc.deductible.split', 'resident_deductible_interval_v1',
                 [('input.fee', '3195.00'), ('input.prior', '5159.00'), ('rule.standard', '550')], '0.00'),
            calc('calc.big_pay.cap_room', 'cap_room_v1',
                 [('rule.cap', '4500'), ('input.prior_paid', '2304.50')], '2195.50'),
            calc('calc.big_pay.capped', 'resident_big_pay_clamp_v1',
                 [('input.base', '3195.00'), ('rule.rate', '0.5'),
                  ('input.prior_paid', '2304.50'), ('rule.cap', '4500'),
                  ('calc.big_pay.cap_room', '2195.50')], '1597.50'),
            calc('calc.big_pay.self', 'big_self_pay_v1',
                 [('input.base', '3195.00'), ('calc.big_pay.capped', '1597.50')], '1597.50'),
            calc('calc.self_pay_all.parts', 'self_pay_all_components_v1',
                 [('calc.deductible.split', '0.00'), ('calc.catalog.total_out_scope', '240.00'),
                  ('calc.big_pay.self', '1597.50')], '1837.50'),
        ],
        fee_items=[
            item('0', '复方丹参滴丸', '440.0000', '440.0000', '0.0000', '0.0000'),
            item('1', '注射用培美曲塞二钠', '400.0000', '360.0000', '40.0000', '40.0000',
                 division_method='ratio', self_pay_ratio='0.1000'),
            item('2', '罗沙司他胶囊', '400.0000', '360.0000', '40.0000', '40.0000',
                 division_method='ratio', self_pay_ratio='0.1000'),
            item('3', '小换药', '60.0000', '0.0000', '60.0000', '0.0000', division_method='full_out'),
            item('4', '单焦点散光型白内障人工晶体', '200.0000', '200.0000', '0.0000', '0.0000'),
            item('5', '单焦点散光型白内障人工晶体', '1935.0000', '1835.0000', '100.0000', '100.0000',
                 division_method='limit', unit_price_limit='1835.0000', limit_source='明细结算时限价'),
        ],
        explanation_evidence=ExplanationEvidence(
            settlement_date=date(2024, 4, 8),
            rule_choices=[
                RuleChoiceGroup(group_id='rules-ROP-RATE', title='大额支付比例',
                                calculation_refs=['calc.big_pay.capped'], field_refs=['T_BigPay'],
                                candidates=[RuleCandidate(
                                    rule_id='ROP-RATE-002', name='门诊大额基金支付比例-其他机构',
                                    value='50', unit='%', version='V2021-01-01',
                                    source='居民门诊待遇参数表', confirmation_status='文档明确-待官方核证',
                                    status='selected', reason='本单机构条件符合', checks=[])]),
                RuleChoiceGroup(group_id='rules-ROP-CAP', title='封顶线',
                                calculation_refs=['calc.big_pay.capped', 'calc.big_pay.cap_room'],
                                field_refs=['T_BigPay'],
                                candidates=[RuleCandidate(
                                    rule_id='ROP-CAP-003', name='门诊基金年度最高支付限额',
                                    value='4500', unit='元/保险年度', version='V2021-01-01',
                                    source='居民门诊待遇参数表', confirmation_status='文档明确-待官方核证',
                                    status='selected', reason='', checks=[])]),
            ]),
        uncertainties=[UncertaintyModel(
            id='u.acc', code='ACCUMULATION_CROSS_HOSPITAL_UNVERIFIED',
            message='交易前累计为院内逐交易自证口径，跨院累计未经核实。',
            affected_fields=['T_FirstPay', 'T_BigPay'])],
        coverage=CoverageSummary(target_field_count=9, independently_explained_count=7,
                                 amount_reconciled_count=9, observed_only_count=2),
        answer_constraints=AnswerConstraints(may_claim_full_explanation=False),
    )


def _public_0408() -> FeeDecompositionPublic:
    return FeeDecompositionPublic.model_validate(to_public_contract_dict(
        _0408_result(), summary_text='', summary_source='template', sanitize=str))


def test_0408_big_pay_answer_has_correct_capped_formula(monkeypatch):
    """评审问题 1 核心断言：0408 大额支付的正确封顶算式结构。

    正确：min(max(round(3195×50%), −2304.50), 2195.50) = 1597.50
    （交易前已支付 2304.50 是最大值下界，不是从取整结果里减去的减项）；
    错误写法 min(round(3195×50%)−2304.50, 2195.50) 不得出现。
    """
    calls = _no_model_calls(monkeypatch)
    public = _public_0408()
    from src.runtime.policy_qa.fee_decomposition.model_explanation import resolve_question_target
    target = resolve_question_target(public, '大额支付金额是怎么算的')
    assert target.field_codes == ['T_BigPay']
    result = explain_decomposition(public, '大额支付金额是怎么算的')
    assert calls == []
    assert result.evidence_answer_status == 'rendered'
    answer = result.answer
    # 金额与采用比例、剩余额度及其作用都在正文
    assert '1597.50' in answer
    assert '3195.00' in answer
    assert '50%' in answer
    assert '2195.50' in answer
    assert '封顶 4500 元－交易前已支付 2304.50 元' in answer
    # 正确结构：取整结果与负下界是最大值的两个操作数
    assert '取整（基数 3195.00 元×比例 0.5），－交易前已支付 2304.50 元' in answer
    # 错误结构：把交易前已支付当成取整结果的减项
    assert '取整（基数 3195.00 元×比例 0.5）－2304.50' not in answer
    assert '0.5）－2304.50' not in answer
    # 跨院累计未核实声明不再进入正文（保留在 uncertainties/citations 供审计）
    assert '跨院累计未经核实' not in answer


def test_0408_deductible_zero_explains_prior_accumulation_covers_standard(monkeypatch):
    """0408 起付 0：说明交易前累计 5159 已覆盖 550 起付标准。"""
    calls = _no_model_calls(monkeypatch)
    result = explain_decomposition(_public_0408(), '本次起付金额是多少')
    assert calls == []
    assert '0.00' in result.answer
    assert '5159' in result.answer
    assert '550' in result.answer
    assert '已达到起付标准' in result.answer


def test_0408_self_pay_2_composition_is_180_equals_40_40_100(monkeypatch):
    """0408 自付二 180=40+40+100（两笔比例先行 40+人工晶体超限价 100）；
    小换药 60 属于全自费，已计医保外、不计入自付二。"""
    calls = _no_model_calls(monkeypatch)
    result = explain_decomposition(_public_0408(), '自付二为什么这么多')
    assert calls == []
    assert '180.00' in result.answer
    assert '40.00' in result.answer
    assert '100.00' in result.answer
    assert '全自费' in result.answer
    assert '不计入自付二' in result.answer
    assert '小换药' in result.answer


@pytest.mark.parametrize("junk", [
    '1597.50元是现金支付',
    '现金支付（元）：1597.50',
    '现金支付为3435',
    '本单现金支付比例为50%',
    '居民门诊本单按统筹基金90%报销',
])
def test_0408_model_free_text_never_enters_fee_decomposition_answer(monkeypatch, junk):
    """评审问题 1 指定反例：模型替身自由文本一律不得进入费用分解正文。"""
    calls = []
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *args, **kwargs: calls.append(1) or SimpleNamespace(content=junk))
    public = _public_0408()
    baseline = explain_decomposition(public, '大额支付金额是怎么算的')
    result = explain_decomposition(public, '大额支付金额是怎么算的')
    assert calls == []
    assert result.answer == baseline.answer
    # 逐条核验垃圾文本的关键错误声明未进入正文
    assert '现金支付（元）' not in result.answer
    assert '现金支付为3435' not in result.answer
    assert '现金支付比例' not in result.answer
    assert '90%' not in result.answer
    assert '统筹基金' not in result.answer  # 居民门诊无统筹基金渠道
    assert '1597.50元是现金支付' not in result.answer
    # 正确事实块完整在正文
    assert '大额支付 1597.50 元' in result.answer


def test_0408_model_config_timeout_and_error_content_keep_same_fact_block(monkeypatch):
    """模型未配置/超时/错误内容都不能改变可信事实块。"""
    from src.model_service.exceptions import ModelConfigError, ModelTimeoutError

    public = _public_0408()
    baseline = explain_decomposition(public, '大额支付金额是怎么算的')
    assert baseline.evidence_answer_status == 'rendered'

    def raise_config(*args, **kwargs):
        raise ModelConfigError('no route', model_name='test-model')

    def raise_timeout(*args, **kwargs):
        raise ModelTimeoutError('timeout', model_name='test-model')

    for stub in (raise_config, raise_timeout,
                 lambda *args, **kwargs: SimpleNamespace(content=' min(round(3195×50%)-2304.50,2195.50)=1597.50 ')):
        monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate', stub)
        result = explain_decomposition(public, '大额支付金额是怎么算的')
        assert result.answer == baseline.answer
        assert result.evidence_answer_status == 'rendered'
        assert result.used_model is False


# ── 688 分桶与 567 分段：确定性正文按计算记录给出真实分量构成 ──


def _public_special_688():
    """居民门特 688 形态：大病支付 226.96＝医保内分桶 181.53＋医保外分桶 45.43。

    对应 .scratch/four-chains-quality-2026-10-21/resident-special.json 的二次保障结构：
    分桶分量作为 calc.secondary.big_ill_pay 的操作数（各带 calculation_ref 指向分量计算）。
    """
    def calc(cid, formula, result, operands=()):
        return dict(calculation_id=cid, formula_id='x', formula_version='v1', formula=formula,
                    display_name=cid, layout='generic', operands=list(operands),
                    result=result, explainable=True)

    return FeeDecompositionPublic.model_validate(dict(
        schema_version='1.6', algorithm_version='resident_outpatient_special_v1',
        execution_status='complete', reconciliation_status='matched',
        fields=[
            dict(field_code='BIG_ILL_PAY', label='大病支付', observed_amount='226.9600',
                 calculated_amount='226.9600', check_type='independent_recalculation',
                 check_status='matched', explanation_level='amount_reconciled',
                 explainable=True, calculation_refs=['calc.secondary.big_ill_pay']),
            dict(field_code='FEEIN_DB_PAY', label='医保内个人自付一的大病支付',
                 observed_amount='181.5300', calculated_amount='181.53',
                 check_type='independent_recalculation', check_status='matched',
                 explanation_level='amount_reconciled', explainable=True,
                 calculation_refs=['calc.secondary.feein_db_pay']),
            dict(field_code='FEEOUT_DB_PAY', label='按比例先行自付的大病支付',
                 observed_amount='45.4300', calculated_amount='45.4300',
                 check_type='independent_recalculation', check_status='matched',
                 explanation_level='amount_reconciled', explainable=True,
                 calculation_refs=['calc.secondary.feeout_db_pay']),
        ],
        calculations=[
            calc('calc.secondary.big_ill_pay',
                 '大病保险支付合计＝大病支付（医保内） 181.53 ＋ 大病支付（医保外） 45.4300＝226.9600 元',
                 '226.9600',
                 [dict(display_name='大病支付（医保内）', value='181.53',
                       calculation_ref='calc.secondary.feein_db_pay'),
                  dict(display_name='大病支付（医保外）', value='45.4300',
                       calculation_ref='calc.secondary.feeout_db_pay')]),
            calc('calc.secondary.feein_db_pay', '大病支付（医保内）＝181.53 元', '181.53'),
            calc('calc.secondary.feeout_db_pay', '大病支付（医保外）：按本单结算记录采用 45.4300 元', '45.4300'),
        ],
        fee_items=[], uncertainties=[], sources=[], path_steps=[], formula_inputs=[],
    ))


def test_688_big_pay_answer_gives_bucket_composition(monkeypatch):
    """688：确定性正文直接给出大病支付的分桶构成 226.96＝181.53＋45.43。"""
    calls = _no_model_calls(monkeypatch)
    result = explain_decomposition(_public_special_688(), '大病支付为什么是226.96元？')
    assert calls == []
    assert result.evidence_answer_status == 'rendered'
    assert '226.96' in result.answer
    assert '181.53' in result.answer and '45.43' in result.answer
    assert '医保内' in result.answer and '医保外' in result.answer


def _public_special_567_two_segments():
    """职工门特 567 退休补助真实投影：211.50＝统筹自付 423×50%（上游公式进 brief/正文）。"""

    def calc(cid, fid, pairs, result):
        return CalculationRecordModel(
            calculation_id=cid, formula_id=fid, formula_version='v1',
            operands=[CalculationOperandModel(ref=ref, value=value) for ref, value in pairs],
            result=result)

    def field(code, label, value, refs):
        return FieldExplanationModel(
            field_code=code, label=label, check_type='independent_recalculation',
            check_status='matched', observed_amount=value, calculated_amount=value,
            difference='0.00', explanation_level='causally_explained', calculation_refs=refs)

    result = SettlementDecompositionResult(
        settlement_ref='settlement:567', algorithm_version='employee_outpatient_special_v1',
        profile=DecompositionProfile(insurance_type='employee', medical_category='special'),
        execution_status='complete', reconciliation_status='matched',
        fields=[
            field('BCZHF', '退休补充保险补助', '211.50', ['calc.rsup.amount']),
            field('TCZIF', '统筹自付', '423.00', ['calc.pool.self_pay']),
        ],
        calculations=[
            calc('calc.pool.self_pay', 'special_pool_self_pay_v1', [('input.pool_self', '423.00')], '423.00'),
            calc('calc.rsup.pool', 'special_retire_supplement_pool_v1',
                 [('calc.pool.self_pay', '423.00'), ('rule.rsup.rate', '0.5')], '211.50'),
            calc('calc.rsup.big', 'special_retire_supplement_large_v1',
                 [('input.large_self', '0.00'), ('rule.rsup.rate', '0.5')], '0.00'),
            calc('calc.rsup.amount', 'special_retire_supplement_total_v1',
                 [('calc.rsup.pool', '211.50'), ('calc.rsup.big', '0.00')], '211.50'),
        ],
        explanation_evidence=ExplanationEvidence(
            settlement_date=date(2025, 5, 6),
            rule_choices=[RuleChoiceGroup(
                group_id='rules-ESP-RSUP', title='退休补助比例',
                calculation_refs=['calc.rsup.pool', 'calc.rsup.amount'], field_refs=['BCZHF'],
                candidates=[RuleCandidate(
                    rule_id='ESP-RSUP-001', name='退休补助-普通退休-统筹共付段',
                    value='50', unit='%', version='2024-04-30', source='ESP-RSUP 参数表',
                    confirmation_status='文档明确-待官方核证', status='selected',
                    reason='本单为退休人员', checks=[])])]),
        coverage=CoverageSummary(target_field_count=2, independently_explained_count=2,
                                 amount_reconciled_count=2, observed_only_count=0),
        answer_constraints=AnswerConstraints(may_claim_full_explanation=True),
    )
    return FeeDecompositionPublic.model_validate(to_public_contract_dict(
        result, summary_text='', summary_source='template', sanitize=str))


def test_567_retire_subsidy_answer_gives_423_half_equals_211_50(monkeypatch):
    """567：退休补助正文含真实构成 423×50%＝211.50（上游公式）与分段合计。"""
    calls = _no_model_calls(monkeypatch)
    public = _public_special_567_two_segments()
    result = explain_decomposition(public, '退休补助211.50元怎么算的？')
    assert calls == []
    assert result.evidence_answer_status == 'rendered'
    # 构成：423（本段个人自付）× 50%（采用档）＝ 211.50
    assert '423.00' in result.answer
    assert '本段个人自付 423.00 元×退休补助比例 0.5' in result.answer
    assert '211.50' in result.answer
    assert ('50%' in result.answer) or ('0.5' in result.answer)
    # 侧栏 brief 与聊天同源：同一份构成文字
    field = next(f for f in public.fields if f.field_code == 'BCZHF')
    assert field.explanation is not None
    assert '本段个人自付 423.00 元×退休补助比例 0.5' in (field.explanation.composition or '')
    assert '经' not in (field.explanation.composition or '') or '可展开查看' not in (field.explanation.composition or '')


# ── 任务 10：逐目标验收（禁止关键词假通过）──────────────────────────

def _acceptance_requirements(public) -> list:
    """把公开投影的展示字段转成验收要求：可解释/原单事实/不适用三类。"""
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_acceptance_grading import (
        TargetRequirement)
    requirements = []
    for field in public.fields:
        if not field.field_code or '.' in field.field_code:
            continue
        if field.check_status == 'not_applicable':
            kind = 'not_applicable'
        elif field.explainable:
            kind = 'explainable'
        else:
            kind = 'observed_only'
        requirements.append(TargetRequirement(
            key=field.field_code, label=field.label, amount=field.observed_amount, kind=kind))
    return requirements


def _acceptance_summary(public, question: str):
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_acceptance_grading import (
        acceptance_summary)
    answer = explain_decomposition(public, question).answer
    citations = tuple(source.title for source in public.sources if source.title)
    return answer, acceptance_summary(answer, _acceptance_requirements(public), citations)


def test_0408_cover_all_delivers_every_visible_field_target(monkeypatch):
    """0408 全覆盖：每个展示字段都有绑定金额的交付，不整题吞掉已有证据。"""
    calls = _no_model_calls(monkeypatch)
    public = _public_0408()
    answer, summary = _acceptance_summary(public, '请解释这张结算单的全部费用，逐项说明所有展示金额')
    assert calls == []
    assert summary['missing_evidence'] == []
    # 可解释字段进入原因解释；账面勾稽字段只算原单事实，两者不混计
    assert 'T_BigPay' in summary['reason_explained']
    assert 'T_CashPay' in summary['book_fact']
    assert 'T_PersonCountPay' in summary['book_fact']
    # 金额绑定：1837.50 属个人支付，不在大额支付句内
    big_pay_line = next(line for line in answer.splitlines() if '大额支付' in line)
    assert '1597.50' in big_pay_line and '1837.50' not in big_pay_line


def test_0408_self_pay_2_target_delivers_180_equals_40_40_100():
    """0408 自付二 180＝40+40+100：目标交付含本单实际构成，不是只报总额。"""
    from src.runtime.policy_qa.fee_decomposition.model_explanation import (
        build_self_pay_2_breakdown)
    public = _public_0408()
    breakdown = build_self_pay_2_breakdown(public)
    assert breakdown.total == '180.00'
    assert [line.amount for line in breakdown.lines] == ['40.00', '40.00', '100.00']
    # 小换药 60 属全自费，已计医保外，不进自付二
    assert [line.label for line in breakdown.full_out_items] == ['小换药']
    answer = explain_decomposition(public, '个人支付自付（二）金额是怎么算的？').answer
    assert '180.00' in answer


def test_567_retire_subsidy_target_is_reason_explained():
    public = _public_special_567_two_segments()
    answer, summary = _acceptance_summary(public, '退休补助211.50元怎么算的？')
    assert 'BCZHF' in summary['reason_explained']
    assert '423.00' in answer and '211.50' in answer
    assert ('50%' in answer) or ('0.5' in answer)


def test_688_secondary_coverage_targets_are_reason_explained():
    public = _public_special_688()
    answer, summary = _acceptance_summary(public, '大病保险支付226.96元怎么算的？')
    big_ill = next(field for field in public.fields if field.label in ('大病支付', '大病保险支付'))
    assert big_ill.field_code in summary['reason_explained'] + summary['book_fact']
    assert '226.96' in answer


def test_cover_all_never_calls_a_book_fact_a_reason():
    """全覆盖里账面勾稽/渠道字段只能算原单事实，不得并入原因解释通过率。"""
    public = _public_0408()
    answer, summary = _acceptance_summary(public, '请解释全部费用，逐个说明所有展示金额')
    for key in summary['book_fact']:
        assert key not in summary['reason_explained']
    # 每个展示字段都至少被交付（原因/事实/不适用），不因个别缺证整题吞掉
    delivered = set(sum(summary.values(), []))
    assert {field.field_code for field in public.fields if '.' not in field.field_code} <= delivered
    assert answer.count('- ') >= len(delivered)


# ── R2/R3（2026-10-27）：数值保真与证据展示资格 ─────────────────────

def _precision_result(*, item_unit="80.00", item_qty="0.125", item_fee="10.00",
                      field_observed="60.00", field_calculated="50.00",
                      field_status="mismatched", extra_calc=None):
    """构造完整分解结果：一个字段 + 一行明细，由公开投影决定 explainable。"""
    def calc(cid, fid, pairs, result, rounding_rule=None):
        return CalculationRecordModel(
            calculation_id=cid, formula_id=fid, formula_version='v1',
            operands=[CalculationOperandModel(ref=ref, value=value) for ref, value in pairs],
            result=result, rounding_rule=rounding_rule)

    calculations = [calc('calc.fund.part', 'public_medical_topup_v1',
                         [('input.base', '100.00'), ('rule.rate', '0.5'), ('input.paid', '0.00')],
                         '50.00')]
    if extra_calc is not None:
        calculations.append(extra_calc)
    return SettlementDecompositionResult(
        settlement_ref='settlement:precision', algorithm_version='employee_outpatient_v1',
        profile=DecompositionProfile(insurance_type='employee', medical_category='outpatient'),
        execution_status='partial', reconciliation_status='not_verifiable',
        fields=[FieldExplanationModel(
            field_code='T_FeeAll', label='费用总金额', check_type='independent_recalculation',
            check_status=field_status, observed_amount=field_observed,
            calculated_amount=field_calculated,
            difference=str(Decimal(field_calculated) - Decimal(field_observed)),
            explanation_level='causally_explained' if field_status == 'matched' else 'observed',
            calculation_refs=['calc.fund.part'])],
        calculations=[
            calc('calc.catalog.total_fee', 'catalog_total_fee_v1', [], item_fee),
            calc('calc.catalog.total_in_scope', 'catalog_total_in_scope_v1', [], item_fee),
            calc('calc.catalog.total_out_scope', 'catalog_total_out_scope_v1', [], '0.00'),
            calc('calc.catalog.total_self_pay_2', 'catalog_total_self_pay_2_v1', [], '0.00'),
            *calculations,
        ],
        fee_items=[FeeItemExplanation(
            line_id='0', item_name='精度测试项目', unit_price=item_unit, quantity=item_qty,
            total_fee=item_fee, observed_in_scope='439.00', observed_out_scope='0.00',
            observed_self_pay_2='0.00', calculated_in_scope=item_fee,
            calculated_out_scope='0.00', calculated_self_pay_2='0.00', status='calculated',
            verification_status='verified')],
        coverage=CoverageSummary(target_field_count=1, independently_explained_count=0,
                                 amount_reconciled_count=0, observed_only_count=1),
        answer_constraints=AnswerConstraints(may_claim_full_explanation=False),
    )


def _public_from(result) -> FeeDecompositionPublic:
    return FeeDecompositionPublic.model_validate(to_public_contract_dict(
        result, summary_text='', summary_source='template', sanitize=str))


def test_r2_quantity_and_unit_price_keep_effective_precision(monkeypatch):
    """B1：单价 80、数量 0.125、费用 10，正文不得把数量压成 0.13。"""
    calls = _no_model_calls(monkeypatch)
    public = _public_from(_precision_result())
    result = explain_decomposition(public, '第1行的医保内外怎么算？')
    assert calls == []
    assert '0.125' in result.answer
    assert '0.13' not in result.answer
    # 等式两边数值仍成立：80×0.125=10
    assert Decimal('80') * Decimal('0.125') == Decimal('10.00')


def test_r2_fine_ratio_and_version_text_are_not_rounded(monkeypatch):
    """B2：比例 0.0005、版本 2024.0101、代码 12.34567 不被全局舍入。"""
    from src.runtime.policy_qa.fee_decomposition.field_explanations import FieldExplanationView

    from src.runtime.policy_qa.fee_decomposition.field_explanations import FieldExplanationView

    _no_model_calls(monkeypatch)
    public = _public_from(_precision_result(field_observed='5.00', field_calculated='5.00',
                                            field_status='matched'))
    field = public.fields[0].model_copy(update=dict(explanation=FieldExplanationView(
        meaning='费用合计，属费用口径。',
        composition='本单按 0.0005 比例计算后为 5.00 元。',
        basis_text='版本 2024.0101；项目编码 12.34567。',
        boundary='比例与代码为原文，不做舍入。')))
    public = public.model_copy(update=dict(fields=[field]))
    answer = explain_decomposition(public, '费用总金额是怎么算的？').answer
    assert '0.0005' in answer
    assert '2024.0101' in answer
    assert '12.34567' in answer


def test_r3_unexplained_field_formula_never_enters_the_answer(monkeypatch):
    """B3：账面 60/重算 50 mismatched 时只给原单事实与缺口，不追加候选公式。"""
    calls = _no_model_calls(monkeypatch)
    public = _public_from(_precision_result())
    field = next(f for f in public.fields if f.field_code == 'T_FeeAll')
    assert field.explainable is False
    answer = explain_decomposition(public, '费用总金额是怎么算的？').answer
    assert calls == []
    assert '60.00' in answer          # 原单事实仍在
    assert '50.00 元' not in answer   # 候选计算不得作为本项原因
    assert '100.00' not in answer
    assert '0.5' not in answer


def test_r3_unexplained_line_formulas_never_enter_line_answer(monkeypatch):
    """B4：行账面医保内 439、候选 440 且不可解释时，不能称本行全纳入 440。"""
    calls = _no_model_calls(monkeypatch)
    result = _precision_result()
    result = result.model_copy(update=dict(
        fields=[],
        fee_items=[result.fee_items[0].model_copy(update=dict(
            formulas=['本行全部纳入医保内：440.00 元'],
            decision_path=[FeeItemDecision(
                code='catalog_match', label='药品目录匹配', operator='count_eq',
                actual='1', expected='有效目录条目', outcome='unknown')]))]))
    public = _public_from(result)
    assert public.fee_items[0].explainable is False
    answer = explain_decomposition(public, '第1行的医保内外怎么算？').answer
    assert calls == []
    assert '439.00' in answer
    assert '440.00' not in answer
    assert '本行全部纳入医保内' not in answer


def test_r3_mixed_and_cover_all_do_not_bypass_eligibility(monkeypatch):
    """B6：mixed/cover_all 也走同一资格入口；已有事实保留、缺证仍列出。"""
    calls = _no_model_calls(monkeypatch)
    public = _public_from(_precision_result())
    for question in ('费用总金额和第1行的医保内外各是多少',
                     '请解释全部费用，逐项说明所有展示金额'):
        answer = explain_decomposition(public, question).answer
        assert '100.00' not in answer
        assert '50.00 元' not in answer
        assert '440.00' not in answer
    assert calls == []


def test_r3_grzif1_composition_exception_is_preserved(monkeypatch):
    """GRZIF1 的“补助前分量构成”仍可见（列未维护，不作账面核对），但只取自身终端构成。"""
    calls = _no_model_calls(monkeypatch)
    result = SettlementDecompositionResult(
        settlement_ref='settlement:grzif1', algorithm_version='employee_outpatient_special_v1',
        profile=DecompositionProfile(insurance_type='employee', medical_category='special'),
        execution_status='partial', reconciliation_status='not_verifiable',
        fields=[FieldExplanationModel(
            field_code='GRZIF1', label='个人支付自付（一）金额',
            check_type='independent_recalculation', check_status='not_verifiable',
            observed_amount=None, calculated_amount='1723.0000', difference=None,
            explanation_level='observed',
            reason_code='SELF_PAY_1_BOOK_COLUMN_UNMAINTAINED',
            calculation_refs=['calc.unrelated', 'calc.self_pay_1.parts'])],
        calculations=[
            CalculationRecordModel(
                calculation_id='calc.unrelated', formula_id='catalog_total_fee_v1',
                formula_version='v1',
                operands=[CalculationOperandModel(ref='input.a', value='100.00')],
                result='1723.0000'),
            CalculationRecordModel(
                calculation_id='calc.self_pay_1.parts',
                formula_id='self_pay_1_components_v1', formula_version='v1',
                operands=[CalculationOperandModel(ref='input.first_pay', value='0.0000'),
                          CalculationOperandModel(ref='input.big_self', value='1723.0000')],
                result='1723.0000'),
        ],
        coverage=CoverageSummary(target_field_count=1, independently_explained_count=0,
                                 amount_reconciled_count=0, observed_only_count=1),
        answer_constraints=AnswerConstraints(may_claim_full_explanation=False))
    public = _public_from(result)
    field = next(f for f in public.fields if f.field_code == 'GRZIF1')
    assert field.explainable is False
    answer = explain_decomposition(public, '个人支付自付（一）金额是怎么算的？').answer
    assert calls == []
    assert '1723' in answer
    assert '不作账面核对' in answer          # 边界保留
    # 自身终端构成可见（分量相加），但不得把无关不可解释计算带进来
    assert '100.00' not in answer


# ── F1/F2（2026-10-27 复审）：GRZIF1 终端选择 + 未算平行不得声明等式 ────

def _grzif1_result(*, calculations, field_refs=('calc.self_pay_1.parts',), field_amount='1723.0000'):
    from src.runtime.policy_qa.fee_decomposition.fee_items import FeeItemDecision  # noqa: F401
    return SettlementDecompositionResult(
        settlement_ref='settlement:grzif1', algorithm_version='employee_outpatient_special_v1',
        profile=DecompositionProfile(insurance_type='employee', medical_category='special'),
        execution_status='partial', reconciliation_status='not_verifiable',
        fields=[FieldExplanationModel(
            field_code='GRZIF1', label='个人支付自付（一）金额',
            check_type='independent_recalculation', check_status='not_verifiable',
            observed_amount=None, calculated_amount=field_amount, difference=None,
            explanation_level='observed',
            reason_code='SELF_PAY_1_BOOK_COLUMN_UNMAINTAINED',
            calculation_refs=list(field_refs))],
        calculations=calculations,
        coverage=CoverageSummary(target_field_count=1, independently_explained_count=0,
                                 amount_reconciled_count=0, observed_only_count=1),
        answer_constraints=AnswerConstraints(may_claim_full_explanation=False))


def _calc(cid, fid, pairs, result, explainable=True):
    return CalculationRecordModel(
        calculation_id=cid, formula_id=fid, formula_version='v1',
        operands=[CalculationOperandModel(ref=ref, value=value) for ref, value in pairs],
        result=result, explainable=explainable)


def _grzif1_answer(result) -> str:
    public = _public_from(result)
    return explain_decomposition(public, '个人支付自付（一）金额是怎么算的？').answer


def _grzif1_calcs(terminal_first=False, insert_unrelated=False,
                  upstream_explainable=True, missing_upstream=False,
                  terminal_result='1723.0000'):
    upstream = _calc('calc.pay.parts', 'special_pool_self_pay_v1',
                     [('input.base', '1723.0000')], '1723.0000',
                     explainable=upstream_explainable)
    terminal = _calc('calc.self_pay_1.parts', 'self_pay_1_components_v1',
                     [(('calc.missing' if missing_upstream else 'calc.pay.parts'), '1723.0000')],
                     terminal_result)
    unrelated = _calc('calc.unrelated', 'catalog_total_fee_v1',
                      [('input.a', '100.00')], '100.00')
    calcs = [terminal, upstream] if terminal_first else [upstream, terminal]
    if insert_unrelated:
        calcs = [unrelated, *calcs]
    return calcs


def test_f1_grzif1_terminal_is_not_chosen_by_array_order(monkeypatch):
    """F1：只倒序 calculations，正文必须仍是本字段自己的构成，不得把无关记录带入。"""
    _no_model_calls(monkeypatch)
    forward = _grzif1_answer(_grzif1_result(calculations=_grzif1_calcs()))
    reversed_answer = _grzif1_answer(
        _grzif1_result(calculations=_grzif1_calcs(terminal_first=True)))
    assert '1723' in forward and '1723' in reversed_answer
    assert '100.00' not in forward and '100.00' not in reversed_answer
    assert forward == reversed_answer


def test_f1_grzif1_ignores_unrelated_inserted_records(monkeypatch):
    """F1：无关记录插在终端前后都不能被选中。"""
    _no_model_calls(monkeypatch)
    answer = _grzif1_answer(_grzif1_result(
        calculations=_grzif1_calcs(terminal_first=True, insert_unrelated=True)))
    assert '100.00' not in answer
    assert '1723' in answer


def test_f1_grzif1_terminal_result_mismatch_keeps_facts_and_gap(monkeypatch):
    """F1：终端结果与字段金额不一致 → 不展示构成算式，保留事实与缺项。"""
    _no_model_calls(monkeypatch)
    answer = _grzif1_answer(_grzif1_result(
        calculations=_grzif1_calcs(terminal_result='999.0000')))
    assert '999' not in answer
    assert '1723' in answer
    assert '不作账面核对' in answer
    assert '未核对' in answer or '缺失' in answer


def test_f1_grzif1_missing_upstream_keeps_facts_and_gap(monkeypatch):
    """F1：上游计算缺失 → 不追加候选算式。"""
    _no_model_calls(monkeypatch)
    answer = _grzif1_answer(_grzif1_result(
        calculations=_grzif1_calcs(missing_upstream=True)))
    assert '模型' not in answer
    assert '1723' in answer
    assert '未核对' in answer or '缺失' in answer


def test_f1_grzif1_unexplained_upstream_keeps_facts_and_gap(monkeypatch):
    """F1：上游未算平 → 不把该构成当作已解释。"""
    _no_model_calls(monkeypatch)
    answer = _grzif1_answer(_grzif1_result(
        calculations=_grzif1_calcs(upstream_explainable=False)))
    assert '1723' in answer
    assert '未核对' in answer or '缺失' in answer


def test_f1_grzif1_real_688_composition_survives_reversed_calculations(monkeypatch):
    """F1：真实 688 GRZIF1 构成在倒序后仍保留（279.27＝0＋279.27）。"""
    _no_model_calls(monkeypatch)
    from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence
    from src.runtime.policy_qa.fee_decomposition.public_view import build_public_view_dict
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_resident_outpatient_special import (
        _snapshot, _split)
    from src.runtime.policy_qa.fee_decomposition.resident_outpatient_special import (
        decompose_resident_outpatient_special)

    snapshot = _snapshot()
    result = decompose_resident_outpatient_special(snapshot, _split())
    forward = build_public_view_dict(attach_evidence(result, snapshot),
                                     summary_text='', summary_source='template')
    reversed_view = build_public_view_dict(
        attach_evidence(result.model_copy(update=dict(
            calculations=list(reversed(result.calculations)))), snapshot),
        summary_text='', summary_source='template')
    answers = []
    for view in (forward, reversed_view):
        public = FeeDecompositionPublic.model_validate(view)
        answers.append(explain_decomposition(public, '个人支付自付（一）金额是怎么算的？').answer)
    assert answers[0] == answers[1]
    assert '279.27' in answers[0]
    assert '不作账面核对' in answers[0]


# ── F2：未算平行不得声明“单价×数量＝费用” ─────────────────────────

def _line_public(*, fee='11.00', in_scope='11.00', price='80', quantity='0.125',
                 explainable=False, formulas=()):
    return FeeDecompositionPublic.model_validate(dict(
        schema_version='1.6', algorithm_version='employee_outpatient_v1',
        execution_status='partial', reconciliation_status='not_verifiable',
        fields=[dict(field_code='T_FeeAll', label='费用总金额', observed_amount=fee,
                     calculated_amount=fee, check_type='detail_aggregation',
                     check_status='matched', explanation_level='amount_reconciled',
                     explainable=True)],
        fee_items=[dict(
            line_id='0', item_name='测试项目', unit_price=price, quantity=quantity,
            total_fee=fee, observed_in_scope=in_scope, observed_out_scope='0.00',
            observed_self_pay_2='0.00', status='calculated', explainable=explainable,
            division_method='full_in', formulas=list(formulas))]))


def test_f2_unexplained_line_does_not_claim_equation():
    """F2：费用 11 ≠ 80×0.125，且本行未算平 → 只并列原单事实，不写等式。"""
    answer = explain_decomposition(_line_public(), '第1行的医保内外怎么算？').answer
    assert '11.00' in answer
    assert '80' in answer and '0.125' in answer
    assert '＝单价' not in answer
    assert '11.00 元＝' not in answer


def test_f2_explained_line_keeps_valid_equation():
    """F2 正例：80×0.125＝10 且本行已核对 → 保留等式。"""
    answer = explain_decomposition(
        _line_public(fee='10.00', in_scope='10.00', explainable=True),
        '第1行的医保内外怎么算？').answer
    assert '10.00 元＝单价 80 元×数量 0.125' in answer


def test_f2_line_with_mismatched_product_is_not_an_equation():
    """F2：即使行可解释，乘积与账面费用不等时也不能写等式。"""
    answer = explain_decomposition(
        _line_public(fee='11.00', in_scope='11.00', explainable=True),
        '第1行的医保内外怎么算？').answer
    assert '＝单价' not in answer


def test_f2_mixed_and_cover_all_lines_have_no_false_equation():
    """F2：mixed / cover_all 的最终正文同样不得出现错误等式。"""
    public = _line_public()
    for question in ('费用总金额和第1行的医保内外各是多少',
                     '请解释全部费用，逐项说明所有展示金额'):
        answer = explain


# ── F1（2026-10-27 复审）：GRZIF1 按归属/终端类型/结果/依赖选择 ──────

def _calc(cid, fid, pairs, result, explainable=True):
    return CalculationRecordModel(
        calculation_id=cid, formula_id=fid, formula_version='v1',
        operands=[CalculationOperandModel(ref=ref, value=value) for ref, value in pairs],
        result=result, explainable=explainable)


def _grzif1_result(calculations, field_refs=('calc.self_pay_1.parts',),
                   field_amount='1723.0000'):
    return SettlementDecompositionResult(
        settlement_ref='settlement:grzif1', algorithm_version='employee_outpatient_special_v1',
        profile=DecompositionProfile(insurance_type='employee', medical_category='special'),
        execution_status='partial', reconciliation_status='not_verifiable',
        fields=[FieldExplanationModel(
            field_code='GRZIF1', label='个人支付自付（一）金额',
            check_type='independent_recalculation', check_status='not_verifiable',
            observed_amount=None, calculated_amount=field_amount, difference=None,
            explanation_level='observed',
            reason_code='SELF_PAY_1_BOOK_COLUMN_UNMAINTAINED',
            calculation_refs=list(field_refs))],
        calculations=calculations,
        coverage=CoverageSummary(target_field_count=1, independently_explained_count=0,
                                 amount_reconciled_count=0, observed_only_count=1),
        answer_constraints=AnswerConstraints(may_claim_full_explanation=False))


def _grzif1_calcs(terminal_first=False, insert_unrelated=False,
                  upstream_explainable=True, missing_upstream=False,
                  terminal_result='1723.0000'):
    upstream = _calc('calc.pay.parts', 'special_pool_self_pay_v1',
                     [('input.base', '1723.0000')], '1723.0000',
                     explainable=upstream_explainable)
    terminal = _calc('calc.self_pay_1.parts', 'self_pay_1_components_v1',
                     [(('calc.missing' if missing_upstream else 'calc.pay.parts'), '1723.0000')],
                     terminal_result)
    unrelated = _calc('calc.unrelated', 'catalog_total_fee_v1',
                      [('input.a', '100.00')], '100.00')
    calcs = [terminal, upstream] if terminal_first else [upstream, terminal]
    if insert_unrelated:
        calcs = [unrelated, *calcs]
    return calcs


def _grzif1_answer(result) -> str:
    return explain_decomposition(_public_from(result),
                                 '个人支付自付（一）金额是怎么算的？').answer


def test_f1_grzif1_terminal_is_not_chosen_by_array_order(monkeypatch):
    """F1：只倒序 calculations，正文必须仍是本字段自己的构成，不得把无关记录带入。"""
    _no_model_calls(monkeypatch)
    forward = _grzif1_answer(_grzif1_result(_grzif1_calcs()))
    reversed_answer = _grzif1_answer(
        _grzif1_result(_grzif1_calcs(terminal_first=True)))
    assert '1723' in forward and '1723' in reversed_answer
    assert '100.00' not in forward and '100.00' not in reversed_answer
    assert forward == reversed_answer


def test_f1_grzif1_ignores_unrelated_inserted_records(monkeypatch):
    """F1：无关记录插在终端前后都不能被选中。"""
    _no_model_calls(monkeypatch)
    answer = _grzif1_answer(_grzif1_result(
        _grzif1_calcs(terminal_first=True, insert_unrelated=True)))
    assert '100.00' not in answer
    assert '1723' in answer


def test_f1_grzif1_terminal_result_mismatch_keeps_facts_and_gap(monkeypatch):
    """F1：终端结果与字段金额不一致 → 不展示构成算式，保留事实与缺项。"""
    _no_model_calls(monkeypatch)
    answer = _grzif1_answer(_grzif1_result(
        _grzif1_calcs(terminal_result='999.0000')))
    assert '999' not in answer
    assert '1723' in answer
    assert '不作账面核对' in answer
    assert '未核对' in answer or '缺失' in answer


def test_f1_grzif1_missing_upstream_keeps_facts_and_gap(monkeypatch):
    """F1：上游计算缺失 → 不追加候选算式。"""
    _no_model_calls(monkeypatch)
    answer = _grzif1_answer(_grzif1_result(
        _grzif1_calcs(missing_upstream=True)))
    assert '1723' in answer
    assert '未核对' in answer or '缺失' in answer


def test_f1_grzif1_unexplained_upstream_keeps_facts_and_gap(monkeypatch):
    """F1：上游未算平 → 不把该构成当作已解释。"""
    _no_model_calls(monkeypatch)
    answer = _grzif1_answer(_grzif1_result(
        _grzif1_calcs(upstream_explainable=False)))
    assert '1723' in answer
    assert '未核对' in answer or '缺失' in answer


def test_f1_grzif1_real_688_composition_survives_reversed_calculations(monkeypatch):
    """F1：真实 688 GRZIF1 构成在倒序后仍保留（279.27＝0＋279.27）。"""
    from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence
    from src.runtime.policy_qa.fee_decomposition.public_view import build_public_view_dict
    from src.runtime.policy_qa.fee_decomposition.resident_outpatient_special import (
        decompose_resident_outpatient_special)
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_resident_outpatient_special import (
        _snapshot, _split)

    _no_model_calls(monkeypatch)
    snapshot = _snapshot()
    result = decompose_resident_outpatient_special(snapshot, _split())
    forward = build_public_view_dict(attach_evidence(result, snapshot),
                                     summary_text='', summary_source='template')
    reversed_result = result.model_copy(
        update=dict(calculations=list(reversed(result.calculations))))
    reversed_view = build_public_view_dict(
        attach_evidence(reversed_result, snapshot),
        summary_text='', summary_source='template')
    answers = []
    for view in (forward, reversed_view):
        answers.append(explain_decomposition(
            FeeDecompositionPublic.model_validate(view),
            '个人支付自付（一）金额是怎么算的？').answer)
    assert answers[0] == answers[1]
    assert '279.27' in answers[0]
    assert '不作账面核对' in answers[0]


# ── F2（2026-10-27 复审）：未算平行不得声明“单价×数量＝费用” ──────

def _line_public(*, fee='11.00', in_scope='11.00', price='80', quantity='0.125',
                 explainable=False):
    return FeeDecompositionPublic.model_validate(dict(
        schema_version='1.6', algorithm_version='employee_outpatient_v1',
        execution_status='partial', reconciliation_status='not_verifiable',
        fields=[dict(field_code='T_FeeAll', label='费用总金额', observed_amount=fee,
                     calculated_amount=fee, check_type='detail_aggregation',
                     check_status='matched', explanation_level='amount_reconciled',
                     explainable=True)],
        fee_items=[dict(
            line_id='0', item_name='测试项目', unit_price=price, quantity=quantity,
            total_fee=fee, observed_in_scope=in_scope, observed_out_scope='0.00',
            observed_self_pay_2='0.00', status='calculated', explainable=explainable,
            division_method='full_in', formulas=[])]))


def test_f2_unexplained_line_does_not_claim_equation():
    """F2：费用 11 ≠ 80×0.125，且本行未算平 → 只并列原单事实，不写等式。"""
    answer = explain_decomposition(_line_public(), '第1行的医保内外怎么算？').answer
    assert '11.00' in answer
    assert '80' in answer and '0.125' in answer
    assert '＝单价' not in answer


def test_f2_explained_line_keeps_valid_equation():
    """F2 正例：80×0.125＝10 且本行已核对 → 保留等式。"""
    answer = explain_decomposition(
        _line_public(fee='10.00', in_scope='10.00', explainable=True),
        '第1行的医保内外怎么算？').answer
    assert '10.00 元＝单价 80 元×数量 0.125' in answer


def test_f2_line_with_mismatched_product_is_not_an_equation():
    """F2：即使行可解释，乘积与账面费用不等时也不能写等式。"""
    answer = explain_decomposition(
        _line_public(fee='11.00', in_scope='11.00', explainable=True),
        '第1行的医保内外怎么算？').answer
    assert '＝单价' not in answer


def test_f2_mixed_and_cover_all_lines_have_no_false_equation():
    """F2：mixed / cover_all 的最终正文同样不得出现错误等式。"""
    public = _line_public()
    for question in ('费用总金额和第1行的医保内外各是多少',
                     '请解释全部费用，逐项说明所有展示金额'):
        answer = explain_decomposition(public, question).answer
        assert '＝单价' not in answer


def test_rounding_rule_statement_is_hidden_from_answer_and_uncertainties(monkeypatch):
    """取整规则声明属于内部口径：不进正文，也不在“尚待核实”里重复。"""
    from src.runtime.policy_qa.fee_decomposition.field_explanations import FieldExplanationView

    _no_model_calls(monkeypatch)
    public = _public_from(_precision_result(field_observed='5.00', field_calculated='5.00',
                                            field_status='matched'))
    field = public.fields[0].model_copy(update=dict(explanation=FieldExplanationView(
        meaning='费用合计，属费用口径。',
        composition='按当前口径重算相符。',
        basis_text='取整规则 ROP-RND-001 待确认；本次显式采用 round_half_up。',
        boundary='依据待签核。')))
    public = public.model_copy(update=dict(
        fields=[field],
        uncertainties=[UncertaintyModel(
            id='u.rounding', code='ROUNDING_RULE_PENDING_CONFIRMATION',
            message='取整规则 ROP-RND-001 待确认；本次计算显式采用 round_half_up。',
            affected_fields=['T_FeeAll'])]))
    result = explain_decomposition(public, '费用总金额是怎么算的？')
    assert 'ROP-RND-001' not in result.answer
    assert 'round_half_up' not in result.answer
    assert not any('ROP-RND-001' in message for message in result.uncertainties)
    # 内部物理列名仍须隐藏
    assert 'T_FeeAll' not in result.answer


def test_fact_only_answer_uses_model_with_concise_prompt(monkeypatch):
    """纯原单事实也交模型润色；简洁性由提示词【简洁】约束，不再写死展示。"""
    from src.runtime.policy_qa.fee_decomposition.model_explanation import _load_prompt
    assert "【表达】" in _load_prompt()[0]
    monkeypatch.setenv('FEE_EXPLANATION_MODE', 'structured')
    prose = '现金支付 1837.50 元，是本次个人负担的支付方式。'
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *a, **k: SimpleNamespace(content=prose))
    result = explain_decomposition(_public_0408(), '现金支付是多少')
    assert result.used_model is True
    assert result.answer == prose
def test_big_ill_payload_carries_both_bucket_formulas_and_prompt_asks_for_them():
    """大病支付：两个分桶的算式必须在模型载荷里，提示词要求分别说明。"""
    import json as _json
    from src.runtime.policy_qa.fee_decomposition.model_explanation import _load_prompt
    assert "【费用分解算法" in _load_prompt()[0]
    assert "本桶合规自付" in _load_prompt()[0]
    from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence
    from src.runtime.policy_qa.fee_decomposition.public_view import build_public_view_dict
    from src.runtime.policy_qa.fee_decomposition.resident_outpatient_special import (
        decompose_resident_outpatient_special)
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_resident_outpatient_special import (
        _snapshot, _split)

    snapshot = _snapshot()
    result = decompose_resident_outpatient_special(snapshot, _split())
    public = FeeDecompositionPublic.model_validate(
        build_public_view_dict(attach_evidence(result, snapshot),
                               summary_text='', summary_source='template'))
    payload = build_model_input(public, '大病支付为什么这么多')
    formulas = {calc.calculation_id: (calc.formula or '') for calc in payload.decomposition.calculations}
    assert any('本桶合规自付 279.27' in text and '181.53' in text for text in formulas.values())
    assert any('按本单结算记录采用' in text and '45.43' in text for text in formulas.values())
    # 载荷 JSON 实际会发给模型：确认两个分桶都在序列化结果里
    body = _json.dumps(payload.model_dump(mode='json'), ensure_ascii=False)
    assert '本桶合规自付 279.27' in body and '按本单结算记录采用' in body


def test_structured_mode_falls_back_when_a_bucket_is_missing(monkeypatch):
    """大病支付两个分桶：模型漏掉“医保内 181.53”即回落确定性正文（含两桶算式）。"""
    from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence
    from src.runtime.policy_qa.fee_decomposition.public_view import build_public_view_dict
    from src.runtime.policy_qa.fee_decomposition.resident_outpatient_special import (
        decompose_resident_outpatient_special)
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_resident_outpatient_special import (
        _snapshot, _split)

    snapshot = _snapshot()
    public = FeeDecompositionPublic.model_validate(
        build_public_view_dict(attach_evidence(decompose_resident_outpatient_special(snapshot, _split()),
                                               snapshot),
                               summary_text='', summary_source='template'))
    monkeypatch.setenv('FEE_EXPLANATION_MODE', 'structured')
    partial_prose = ('本单大病支付合计 226.96 元，其中医保外 45.43 元按本单结算记录采用；'
                     '分段支付合计 226.96 元，按 349.17×65% 计算。')
    complete_prose = ('本笔大病支付 226.96 元＝医保内 181.53 元＋医保外 45.43 元；'
                      '医保内 181.53 元＝本桶合规自付 279.27 元×65%；'
                      '医保外 45.43 元＝本桶合规自付 69.90 元×65%，按本单结算记录采用。')
    replies = [partial_prose, complete_prose]
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *a, **k: SimpleNamespace(content=replies.pop(0)))
    result = explain_decomposition(public, '大病支付为什么这么多')
    assert result.used_model is True
    assert result.answer == complete_prose
    assert '181.53' in result.answer and '45.43' in result.answer




def test_answer_drops_parameter_list_and_book_reconciliation(monkeypatch):
    """门诊问题不能接纳门特回答；不能靠删除部分句子把答非所问洗成合规。"""
    monkeypatch.setenv('FEE_EXPLANATION_MODE', 'structured')
    prose = ('本笔大病支付 226.96 元＝医保内 181.53 元＋医保外 45.43 元；'
             '医保内 181.53 元＝本桶合规自付 279.27 元×65%；'
             '医保外 45.43 元＝本桶合规自付 69.90 元×65%。\n'
             '核对关系：181.53＋45.43＝226.96 元，与账面大病支付一致。\n'
             '本次采用：门特起付标准 1300 元、门特大病基金支付比例 75%、封顶线 250000 元。')
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *a, **k: SimpleNamespace(content=prose))
    result = explain_decomposition(_public_0408(), '大额支付为什么这么多')
    assert result.used_model is False
    assert result.fallback_reason == 'validation_rejected'
    assert '本次采用' not in result.answer
    assert '核对关系' not in result.answer and '与账面' not in result.answer


def test_answer_drops_parenthetical_noise_and_parameter_lines(monkeypatch):
    """其他结算链路的公式与金额不能进入当前单，即使数字来自其它已知样例。"""
    monkeypatch.setenv('FEE_EXPLANATION_MODE', 'structured')
    prose = ('大病支付 226.96 元＝医保内 181.53 元＋医保外 45.43 元。\n'
             '医保内分桶：本桶合规自付 279.27 元×65%＝181.53 元（取整到分）。\n'
             '医保外分桶：本桶合规自付 69.90 元×65%＝45.43 元（按本单结算记录采用）。\n'
             '起付线·门特起付标准-老年/无业-三级-年度第一个结算周期1300元/结算周期；'
             '居民门特基金支付比例·门特大病基金支付比例-三级医疗机构75%；'
             '封顶线·居民基金年度最高支付限额（2019起）250000元/保险年度。')
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *a, **k: SimpleNamespace(content=prose))
    result = explain_decomposition(_public_0408(), '大额支付为什么这么多')
    assert result.used_model is False
    assert result.fallback_reason == 'validation_rejected'
    assert '取整到分' not in result.answer
    assert '按本单结算记录采用' not in result.answer
    assert '起付线·' not in result.answer and '封顶线·' not in result.answer
    assert '279.27' not in result.answer and '69.90' not in result.answer
    assert '1597.50' in result.answer
