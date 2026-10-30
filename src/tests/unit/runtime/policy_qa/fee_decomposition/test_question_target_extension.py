"""阶段 D：问法识别扩展（多行/全量/对比/消歧）与会话级追问目标继承。

验收表 8 场景：
1. cover_all（"解释全部费用"/"逐项说明所有明细"），模型输入含全部行证据；
2. multi_line（"第1行和第2行"），两行证据各自独立、金额互不作证；
3. comparison（"自付一和自付二有什么区别"），证据含两字段固定说明与构成差异；
4. 同名项目消歧（"200块那个晶体"/"第5行的晶体"收敛；无线索 ambiguous）；
5. 指代追问继承上一问行目标（同 session 同单）；
6. 换单后不继承；
7. 显式新目标覆盖继承；
8. 回答/回退文本无内部字段名泄漏。
"""
import re
from types import SimpleNamespace

import pytest

from src.runtime.policy_qa.fee_decomposition.followup_target import (
    clear_followup_targets, resolve_session_question_target)
from src.runtime.policy_qa.fee_decomposition.model_explanation import (
    build_model_input, explain_decomposition, resolve_question_target)
from src.runtime.policy_qa.public_contract import FeeDecompositionPublic


def _public_lines():
    """居民门诊形态：6 行明细，第 5/6 行同名人工晶体（200.00 / 1935.00 限价拆分）。"""
    def item(line_id, name, fee, in_scope, out_scope, sp2, **overrides):
        base = dict(line_id=line_id, item_name=name, unit_price=fee, quantity='1.00',
                    total_fee=fee, observed_in_scope=in_scope, observed_out_scope=out_scope,
                    observed_self_pay_2=sp2, status='calculated', explainable=True,
                    division_method='full_in')
        return base | overrides

    def field(code, label, value, explanation=None):
        return dict(field_code=code, label=label, observed_amount=value,
                    calculated_amount=value, check_type='independent_recalculation',
                    check_status='matched', explanation_level='amount_reconciled',
                    explainable=True, explanation=explanation)

    return FeeDecompositionPublic.model_validate(dict(
        schema_version='1.6', algorithm_version='resident_outpatient_v1',
        execution_status='complete', reconciliation_status='matched',
        fields=[
            field('T_FeeAll', '费用总金额', '3435.00'),
            field('T_FeeIn', '医疗保险范围内金额', '3195.00'),
            field('T_FeeOut', '医疗保险范围外金额', '240.00'),
            field('T_SelfPay1', '自付一', '40.00', explanation=dict(
                meaning='医保范围内费用中按待遇政策由个人承担的部分（自付一），属个人负担口径。',
                composition='按待遇比例对医保范围内费用计算。',
                basis_text='依据来源：门诊待遇参数表。', boundary=None)),
            field('T_SelfPay2', '自付二', '100.00', explanation=dict(
                meaning='部分项目按规定比例由个人先行自付的金额（自付二），属个人负担口径。',
                composition='逐行先行自付合计。',
                basis_text='依据来源：明细结算时比例。', boundary=None)),
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
                 formulas=['医保内金额＝结算时限价 1835.0000 元×数量 1.00＝1835.000000 元']),
        ]))


@pytest.fixture(autouse=True)
def _clear_followup_store():
    clear_followup_targets()
    yield
    clear_followup_targets()


# ── 场景 1：全覆盖意图 ─────────────────────────────────────────────


def test_cover_all_intent_loads_all_line_evidence():
    public = _public_lines()
    for question in ('解释全部费用', '逐项说明所有明细', '每条费用都讲一下'):
        assert resolve_question_target(public, question).kind == 'cover_all'
    payload = build_model_input(public, '解释全部费用')
    assert payload.target_kind == 'cover_all'
    assert payload.line_evidence is None
    assert [e.display_no for e in payload.line_evidences] == [1, 2, 3, 4, 5, 6]
    assert len(payload.decomposition.fee_items) == 6


def test_cover_all_answer_covers_fields_and_all_lines(monkeypatch):
    """全覆盖（"解释全部费用"）确定性正文：全字段固定说明 + 逐行证据，不调模型。"""
    called = []
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *args, **kwargs: called.append(1) or SimpleNamespace(content='x'))
    result = explain_decomposition(_public_lines(), '解释全部费用')
    assert called == []
    assert result.used_model is False
    assert result.evidence_answer_status == 'rendered'
    assert '440.00' in result.answer and '1935.00' in result.answer


# ── 场景 2：多行指向 ───────────────────────────────────────────────


def test_multi_line_question_resolves_each_line():
    public = _public_lines()
    target = resolve_question_target(public, '第1行和第2行为什么自费')
    assert target.kind == 'multi_line'
    assert [(line.display_no, line.line_id) for line in target.lines] == [(1, '0'), (2, '1')]
    target = resolve_question_target(public, '第1、2行医保内多少')
    assert target.kind == 'multi_line'
    assert [line.display_no for line in target.lines] == [1, 2]
    assert set(target.lines[0].attributes) == {'observed_in_scope'}


def test_multi_line_model_input_scopes_to_target_lines():
    public = _public_lines()
    payload = build_model_input(public, '第1行和第2行为什么自费')
    assert payload.target_kind == 'multi_line'
    assert payload.line_evidence is None
    assert [e.display_no for e in payload.line_evidences] == [1, 2]
    assert [line.line_id for line in payload.decomposition.fee_items] == ['0', '1']
    assert payload.decomposition.fields == []
    # 其他行金额不进模型资料（第 6 行 1935/1835 不出现）
    dumped = payload.model_dump_json()
    assert '1935' not in dumped
    assert '罗沙司他' not in dumped


def test_multi_line_answer_binds_amounts_to_their_own_lines(monkeypatch):
    """两行证据各自独立：确定性正文逐行给出本行金额（440 属第 1 行、360 属第 2 行）。"""
    public = _public_lines()
    called = []
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *args, **kwargs: called.append(1) or SimpleNamespace(
                            content='第1行医保内360.00元。'))
    result = explain_decomposition(public, '第1行和第2行为什么自费')
    assert called == []
    assert result.used_model is False
    lines = [line for line in result.answer.split('\n') if line.startswith('- 第')]
    line1 = next(line for line in lines if '第 1 行' in line)
    line2 = next(line for line in lines if '第 2 行' in line)
    assert '440.00' in line1 and '360.00' not in line1
    assert '360.00' in line2 and '440.00' not in line2


def test_multi_line_name_mismatch_is_invalid():
    """多行名称校验沿用单行规则：任一行名不符即 invalid。"""
    public = _public_lines()
    target = resolve_question_target(public, '第1行和第2行罗沙司他为什么贵')
    assert target.kind == 'invalid'
    # 逐行就近配对：名称落在第 2 行子句，提示指向第 2 行自身的项目
    assert '第 2 行是「注射用培美曲塞二钠」' in target.prompt


def test_multi_line_out_of_range_is_invalid():
    public = _public_lines()
    target = resolve_question_target(public, '第1行和第9行为什么贵')
    assert target.kind == 'invalid'
    assert '共 6 行' in target.prompt


# ── 场景 3：字段对比 ───────────────────────────────────────────────


def test_comparison_question_loads_both_field_explanations():
    public = _public_lines()
    target = resolve_question_target(public, '自付一和自付二有什么区别')
    assert target.kind == 'comparison'
    assert set(target.field_codes) == {'T_SelfPay1', 'T_SelfPay2'}
    payload = build_model_input(public, '自付一和自付二有什么区别')
    assert payload.target_kind == 'comparison'
    assert {field.field_code for field in payload.decomposition.fields} == {'T_SelfPay1', 'T_SelfPay2'}
    evidence = {item.field_code: item for item in payload.target_evidence}
    assert set(evidence) == {'T_SelfPay1', 'T_SelfPay2'}
    assert '自付一' in evidence['T_SelfPay1'].sentence
    assert '自付二' in evidence['T_SelfPay2'].sentence
    # 口径差异：后端组装的并列/包含关系说明，模型只组织语言
    assert payload.comparison_note
    assert '不重复相加' in payload.comparison_note


def test_comparison_answer_is_deterministic(monkeypatch):
    """对比题正文：后端组装的关系说明 + 两字段固定说明，不调模型。"""
    public = _public_lines()
    called = []
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *args, **kwargs: called.append(1) or SimpleNamespace(content='x'))
    result = explain_decomposition(public, '自付一和自付二有什么区别')
    assert called == []
    assert result.used_model is False
    assert result.evidence_answer_status == 'rendered'
    assert '不重复相加' in result.answer
    assert '40.00' in result.answer and '100.00' in result.answer


def test_two_fields_without_comparison_marker_stay_summary_fields():
    """无对比措辞的多字段问题维持 summary_fields 形态（不升级为 comparison）。"""
    public = _public_lines()
    target = resolve_question_target(public, '自付一和自付二各是多少')
    assert target.kind == 'summary_fields'
    assert set(target.field_codes) == {'T_SelfPay1', 'T_SelfPay2'}


# ── 场景 4：同名项目消歧 ───────────────────────────────────────────


def test_amount_clue_disambiguates_duplicate_item_names():
    public = _public_lines()
    target = resolve_question_target(public, '200块那个人工晶体为什么贵')
    assert target.kind == 'fee_line'
    assert target.display_no == 5
    target = resolve_question_target(public, '1935元的那个人工晶体为什么贵')
    assert target.kind == 'fee_line'
    assert target.display_no == 6


def test_line_number_clue_disambiguates_duplicate_item_names():
    public = _public_lines()
    target = resolve_question_target(public, '第5行的晶体多少钱')
    assert target.kind == 'fee_line'
    assert target.display_no == 5


def test_duplicate_name_without_clue_stays_ambiguous():
    public = _public_lines()
    target = resolve_question_target(public, '人工晶体为什么贵')
    assert target.kind == 'ambiguous'
    assert '第 5 行' in target.prompt and '第 6 行' in target.prompt


# ── 场景 5-7：会话级追问目标继承 ───────────────────────────────────


def test_followup_inherits_previous_line_target():
    public = _public_lines()
    first = resolve_session_question_target(public, '第3行罗沙司他为什么贵', 'sess-1', 'TRADE-1')
    assert first.kind == 'fee_line' and first.display_no == 3
    inherited = resolve_session_question_target(public, '那这项为什么自费', 'sess-1', 'TRADE-1')
    assert inherited.kind == 'fee_line'
    assert inherited.display_no == 3
    assert inherited.line_id == '2'


def test_followup_does_not_inherit_across_settlements():
    public = _public_lines()
    resolve_session_question_target(public, '第3行罗沙司他为什么贵', 'sess-1', 'TRADE-1')
    other = resolve_session_question_target(public, '那这项为什么自费', 'sess-1', 'TRADE-2')
    assert other.kind == 'whole_settlement'


def test_explicit_new_target_overrides_inherited_target():
    public = _public_lines()
    resolve_session_question_target(public, '第3行罗沙司他为什么贵', 'sess-1', 'TRADE-1')
    second = resolve_session_question_target(public, '自付二为什么这么多', 'sess-1', 'TRADE-1')
    assert second.kind == 'summary_fields'
    inherited = resolve_session_question_target(public, '那这项为什么这么多', 'sess-1', 'TRADE-1')
    assert inherited.kind == 'summary_fields'
    assert inherited.field_codes == ['T_SelfPay2']


def test_no_referent_no_inheritance():
    """无指代词的整单问题不继承上一问目标。"""
    public = _public_lines()
    resolve_session_question_target(public, '第3行罗沙司他为什么贵', 'sess-1', 'TRADE-1')
    plain = resolve_session_question_target(public, '为什么花了这么多钱', 'sess-1', 'TRADE-1')
    assert plain.kind == 'whole_settlement'


# ── 场景 8：回答出口无内部字段名 ───────────────────────────────────


_INTERNAL_LEAK = re.compile(
    r'TB_[A-Za-z0-9]|TA_[A-Za-z0-9]|T_[A-Za-z]|GRZIF|GRZFT|BCZHF|TCZHF|TCZIF|'
    r'YBNQFJE|DEGWY|GFYLBCHBX|BIG_ILL_PAY|RETIRE_OFFICER_PAY|PERSON_PAYABLE')


def test_deterministic_answers_have_no_internal_field_names():
    """确定性正文出口无内部字段名/物理列名泄漏（覆盖各问法形态）。"""
    public = _public_lines()
    for question in ('医保内费用为什么这么多', '第1行和第2行为什么自费', '解释全部费用',
                     '自付一和自付二有什么区别', '第 6 行人工晶体为什么贵', '解释这笔结算'):
        result = explain_decomposition(public, question)
        assert result.used_model is False
        assert not _INTERNAL_LEAK.search(result.answer), question


def test_ambiguous_and_invalid_prompts_have_no_internal_field_names():
    public = _public_lines()
    for question in ('人工晶体为什么贵', '第 9 行是什么'):
        target = resolve_question_target(public, question)
        assert target.prompt
        assert not _INTERNAL_LEAK.search(target.prompt)


# ── 评审问题 2/8/9：混合目标、bill.* 模板字段证据、行号名称一致性 ──


def _public_lines_with_bill():
    """在 _public_lines 基础上加展示模板：含未绑定计算的 bill.beyond_cap 字段。"""
    from src.runtime.policy_qa.fee_decomposition.settlement_facts import (
        SettlementDisplayField, SettlementDisplayView, SettlementFactsView)
    public = _public_lines()

    def tf(key, label, field_code, value=None):
        return SettlementDisplayField(
            key=key, label=label, section='transaction', row=1, column=1,
            scope='patient_actual', value=value, field_code=field_code,
            source_kind='record' if field_code else 'unmapped',
            status='available' if field_code else 'unmapped')

    public.settlement_facts = SettlementFactsView(
        chain='outpatient',
        display_template=SettlementDisplayView(
            template_id='resident_outpatient', version='1.0', title='居民门诊结算单',
            layout_status='provisional',
            fields=[
                tf('fee_all', '费用总金额', 'T_FeeAll', '3435.00'),
                tf('fee_in', '医疗保险范围内金额', 'T_FeeIn', '3195.00'),
                tf('fee_out', '医疗保险范围外金额', 'T_FeeOut', '240.00'),
                tf('self_pay_1', '自付一', 'T_SelfPay1', '40.00'),
                tf('self_pay_2', '自付二', 'T_SelfPay2', '100.00'),
                tf('beyond_cap', '大额超封顶金额', None, '0.00'),
            ]))
    public.template_explanations = {
        'beyond_cap': {
            'meaning': '超出大额基金封顶线的金额，属个人负担口径。',
            'composition': None,
            'basis_text': None,
            'boundary': '本字段无独立计算或费用归属映射；超封顶金额的费用归属未经确认，仅按原单列示。',
        },
    }
    return public


# ── 任务 4：字段 + 明细行混合目标 ────────────────────────────────────


def test_mixed_field_and_line_question_keeps_both_targets():
    """"费用总金额和第1行医保内各是多少"：整单总额与该行医保内同时保留，证据各自独立。"""
    public = _public_lines()
    target = resolve_question_target(public, '费用总金额和第1行医保内各是多少')
    assert target.kind == 'mixed'
    assert target.field_codes == ['T_FeeAll']
    assert [line.display_no for line in target.lines] == [1]
    assert target.lines[0].attributes == ['observed_in_scope']
    payload = build_model_input(public, '费用总金额和第1行医保内各是多少')
    assert payload.target_kind == 'mixed'
    assert [e.field_code for e in payload.target_evidence] == ['T_FeeAll']
    assert [e.display_no for e in payload.line_evidences] == [1]
    result = explain_decomposition(public, '费用总金额和第1行医保内各是多少')
    assert result.evidence_answer_status == 'rendered'
    assert '3435.00' in result.answer  # 整单费用总金额
    assert '440.00' in result.answer   # 第 1 行医保内


def test_mixed_question_does_not_drag_line_attributes_into_summary_fields():
    """混合问法里"医保内"是行属性，不得把整单医保内合计字段拉进目标。"""
    public = _public_lines()
    target = resolve_question_target(public, '费用总金额和第1行医保内各是多少')
    assert 'T_FeeIn' not in target.field_codes


def test_single_line_attribute_question_stays_line_only():
    """单行问题仍只解释本行：不混入整单医保内合计（3195 不进正文）。"""
    public = _public_lines()
    target = resolve_question_target(public, '第1行医保内金额是多少')
    assert target.kind == 'fee_line'
    result = explain_decomposition(public, '第1行医保内金额是多少')
    assert '440.00' in result.answer
    assert '3195' not in result.answer


def test_cover_all_with_named_line_keeps_full_coverage():
    """"解释全部费用，包含第1行的医保内外"：全覆盖含义不被点名行裁掉。"""
    public = _public_lines_with_bill()
    target = resolve_question_target(public, '请解释全部费用，包含第1行的医保内外和每一个展示金额')
    assert target.kind == 'cover_all'
    # 全覆盖集合 = 可见模板字段（含 bill.*）∪ 主字段
    assert 'T_FeeAll' in target.field_codes
    assert 'bill.beyond_cap' in target.field_codes
    payload = build_model_input(public, '请解释全部费用，包含第1行的医保内外和每一个展示金额')
    assert [e.display_no for e in payload.line_evidences] == [1, 2, 3, 4, 5, 6]
    result = explain_decomposition(public, '请解释全部费用，包含第1行的医保内外和每一个展示金额')
    assert result.evidence_answer_status == 'rendered'
    assert '3435.00' in result.answer      # 整单总额
    assert '大额超封顶金额' in result.answer  # bill.* 模板字段也在全覆盖里
    assert '440.00' in result.answer       # 第 1 行
    assert '1935.00' in result.answer      # 第 6 行


def test_mixed_target_is_inheritable_across_followup():
    """混合目标进入追问继承；换单不继承。"""
    public = _public_lines()
    first = resolve_session_question_target(public, '费用总金额和第1行医保内各是多少', 'sess-mix', 'TRADE-1')
    assert first.kind == 'mixed'
    inherited = resolve_session_question_target(public, '那这项呢', 'sess-mix', 'TRADE-1')
    assert inherited.kind == 'mixed'
    assert inherited.field_codes == ['T_FeeAll']
    assert [line.display_no for line in inherited.lines] == [1]
    other = resolve_session_question_target(public, '那这项呢', 'sess-mix', 'TRADE-2')
    assert other.kind == 'whole_settlement'


# ── 任务 5：bill.* 模板字段进入同一份目标证据 ────────────────────────


def test_bill_field_target_binds_template_amount_and_fixed_explanation():
    """bill.* 目标：从模板取名称/金额，从 template_explanations 取固定说明，不补造公式。"""
    public = _public_lines_with_bill()
    target = resolve_question_target(public, '大额超封顶金额是多少')
    assert target.kind == 'summary_fields'
    assert target.field_codes == ['bill.beyond_cap']
    payload = build_model_input(public, '大额超封顶金额是多少')
    evidence = [e for e in payload.target_evidence if e.field_code == 'bill.beyond_cap']
    assert len(evidence) == 1
    assert evidence[0].field_label == '大额超封顶金额'
    assert evidence[0].amount == '0.00'
    assert evidence[0].formula is None  # 归属未经确认：不补造公式
    result = explain_decomposition(public, '大额超封顶金额是多少')
    assert result.evidence_answer_status == 'rendered'
    assert '大额超封顶金额 0.00 元' in result.answer
    assert '仅按原单列示' in result.answer
    assert '计算：' not in result.answer


def test_bill_field_without_template_value_does_not_fabricate_zero():
    """模板字段缺值：缺值不补零，如实说明。"""
    public = _public_lines_with_bill()
    public.settlement_facts.display_template.fields = [
        field.model_copy(update={'value': None})
        if field.key == 'beyond_cap' else field
        for field in public.settlement_facts.display_template.fields]
    result = explain_decomposition(public, '大额超封顶金额是多少')
    assert '大额超封顶金额' in result.answer
    assert '0.00 元' not in result.answer.split('大额超封顶金额')[1].split('。')[0]


def test_bill_field_without_template_explanation_is_honest_gap():
    """模板字段既无映射又无固定说明：缺口如实声明，不借用相邻字段的成功。"""
    public = _public_lines_with_bill()
    public.template_explanations = {}
    result = explain_decomposition(public, '大额超封顶金额是多少')
    assert '大额超封顶金额' in result.answer
    assert '无独立计算或费用归属映射' in result.answer


# ── 任务 6：行号与明确项目名不符时先澄清 ─────────────────────────────


def test_nonexistent_name_with_valid_line_number_is_invalid():
    """"第1行阿莫西林"：名称不存在同样判定不一致（不能只在 hits 非空时校验）。"""
    public = _public_lines()
    target = resolve_question_target(public, '第1行阿莫西林的医保内外怎么算')
    assert target.kind == 'invalid'
    assert '复方丹参滴丸' in target.prompt  # 返回实际行名
    assert '440.00' in target.prompt


def test_quoted_item_name_mismatch_with_line_number_is_invalid():
    """引号中的显式项目名直接核对。"""
    public = _public_lines()
    target = resolve_question_target(public, '第1行「阿莫西林」多少钱')
    assert target.kind == 'invalid'
    assert '复方丹参滴丸' in target.prompt


def test_pure_attribute_question_with_valid_line_number_stays_fee_line():
    """纯属性问题（"第1行医保外怎么算"）按有效行号解释，不当成错误项目名。"""
    public = _public_lines()
    target = resolve_question_target(public, '第1行医保外怎么算')
    assert target.kind == 'fee_line'
    assert target.display_no == 1


def test_line_why_expensive_without_name_stays_fee_line():
    """"第1行为什么贵"：无显式项目名，只说明已有费用及资料中的定价边界。"""
    public = _public_lines()
    target = resolve_question_target(public, '第1行为什么贵')
    assert target.kind == 'fee_line'


def test_explain_both_duplicate_items_keeps_both_lines():
    """"两项都解释"：同名两行保留为 multi_line，不澄清、不丢弃。"""
    public = _public_lines()
    target = resolve_question_target(public, '两个人工晶体都解释一下')
    assert target.kind == 'multi_line'
    assert [line.display_no for line in target.lines] == [5, 6]


def test_conflict_target_short_circuits_without_rendering():
    """名称冲突的目标不进入正文生成（直接返回澄清提示）。"""
    public = _public_lines()
    target = resolve_question_target(public, '第1行阿莫西林的医保内外怎么算')
    result = explain_decomposition(public, '第1行阿莫西林的医保内外怎么算')
    assert result.answer == target.prompt
    assert result.evidence_answer_status == 'none'


def test_mixed_question_with_both_scope_words_is_not_a_wrong_item_name():
    """"第1行的医保内外"是行属性问法，不是项目名；不得误判为名称不符（评审问题 9）。"""
    public = _public_lines()
    target = resolve_question_target(public, '费用总金额和第1行的医保内外各是多少')
    assert target.kind == 'mixed'
    assert target.field_codes == ['T_FeeAll']
    assert [line.display_no for line in target.lines] == [1]
    result = explain_decomposition(public, '费用总金额和第1行的医保内外各是多少')
    assert result.evidence_answer_status == 'rendered'
    assert '未找到名为' not in result.answer
    assert '3435.00' in result.answer


# ── R4/R5（2026-10-27）：局部子句绑定 + 名称/全覆盖不丢目标 ─────────

def test_r4_cover_all_with_named_item_keeps_full_coverage():
    """C1：'解释全部费用，尤其是<项目>' 仍是 cover_all，名称命中不得提前返回。"""
    public = _public_lines()
    target = resolve_question_target(public, '请解释全部费用，尤其是复方丹参滴丸。')
    assert target.kind == 'cover_all'
    assert 'T_FeeAll' in target.field_codes
    assert 'T_FeeIn' in target.field_codes
    payload = build_model_input(public, '请解释全部费用，尤其是复方丹参滴丸。')
    assert [e.display_no for e in payload.line_evidences] == [1, 2, 3, 4, 5, 6]
    answer = explain_decomposition(public, '请解释全部费用，尤其是复方丹参滴丸。').answer
    assert '3435.00' in answer          # 整单金额
    assert '复方丹参滴丸' in answer       # 点名行
    assert '第 6 行' in answer           # 其他行也在全覆盖中


def test_r4_summary_field_with_named_item_is_mixed_both_orders():
    """C2：汇总字段 + 项目名 → mixed；字段在前/在后都保留两类目标。"""
    public = _public_lines()
    for question in ('费用总金额和复方丹参滴丸的费用分别怎么算？',
                     '复方丹参滴丸的费用及费用总金额分别怎么算？'):
        target = resolve_question_target(public, question)
        assert target.kind == 'mixed', question
        assert target.field_codes, question
        assert [line.display_no for line in target.lines] == [1], question
        payload = build_model_input(public, question)
        codes = {e.field_code for e in payload.target_evidence}
        assert 'T_FeeAll' in codes
        assert [e.display_no for e in payload.line_evidences] == [1]


def test_r5_polite_prefix_and_attribute_questions_are_not_item_names():
    """C3/C4：礼貌前缀、数量/单价/金额问法不得被当成项目名拒绝。"""
    public = _public_lines()
    cases = {
        '请解释第1行的医保内外': 'fee_line',
        '麻烦说明第1行医保内外': 'fee_line',
        '第1行的数量、单价和金额分别是什么？': 'fee_line',
    }
    for question, kind in cases.items():
        target = resolve_question_target(public, question)
        assert target.kind == kind, (question, target.kind, target.prompt)
        assert '未找到名为' not in (target.prompt or '')
        answer = explain_decomposition(public, question).answer
        assert '未找到名为' not in answer
    mixed = resolve_question_target(public, '请解释费用总金额以及第1行的医保内金额。')
    assert mixed.kind == 'mixed'
    assert mixed.field_codes == ['T_FeeAll']
    assert [line.display_no for line in mixed.lines] == [1]


def test_r5_swapped_line_name_pairs_are_rejected():
    """C5：行号与名称逐对核验；两行名称互换必须拒绝，不能核对成功。"""
    public = _public_lines()
    # 第1行=复方丹参滴丸，第2行=注射用培美曲塞二钠；这里故意互换
    target = resolve_question_target(
        public, '第1行注射用培美曲塞二钠和第2行复方丹参滴丸各怎么算？')
    assert target.kind == 'invalid'
    assert '未找到名为' in (target.prompt or '') or '不符' in (target.prompt or '')
    # 正确配对仍可回答
    ok = resolve_question_target(
        public, '第1行复方丹参滴丸和第2行注射用培美曲塞二钠各怎么算？')
    assert ok.kind == 'multi_line'
    assert [line.display_no for line in ok.lines] == [1, 2]


def test_r5_unknown_names_rejected_at_every_ordinal_entry():
    """C6：未知名称在行号与列表编号入口同样被拒绝。"""
    public = _public_lines()
    for question in ('第1行阿莫西林', '1. 阿莫西林', '请解释第1行阿莫西林的医保内外'):
        target = resolve_question_target(public, question)
        assert target.kind == 'invalid', (question, target.kind)


def test_r5_cover_all_does_not_swallow_explicit_wrong_name():
    """C6：'全部费用，尤其第1行阿莫西林' 仍要核对错误定位，不能被 cover_all 吞掉。"""
    public = _public_lines()
    target = resolve_question_target(public, '全部费用，尤其第1行阿莫西林')
    assert target.kind == 'invalid'


def test_c7_duplicate_names_and_scoped_all():
    """C7：'第1、2行全部解释' 只限定两行；同名晶体金额消歧；'为何贵' 歧义。"""
    public = _public_lines()
    multi = resolve_question_target(public, '第1、2行全部解释')
    assert multi.kind == 'multi_line'
    assert [line.display_no for line in multi.lines] == [1, 2]

    both = resolve_question_target(public, '两个人工晶体都解释')
    assert both.kind == 'multi_line'
    assert [line.display_no for line in both.lines] == [5, 6]

    narrowed = resolve_question_target(public, '200元那个人工晶体')
    assert narrowed.kind == 'fee_line'
    assert narrowed.display_no == 5

    ambiguous = resolve_question_target(public, '人工晶体为什么贵')
    assert ambiguous.kind == 'ambiguous'


def test_r5_unknown_name_is_reported_without_attribute_leftovers():
    """名称槽剥离长词优先：'阿莫西林的医保内外' 只把'阿莫西林'当声称名称。"""
    public = _public_lines()
    target = resolve_question_target(public, '第1行阿莫西林的医保内外怎么算？')
    assert target.kind == 'invalid'
    assert '「阿莫西林」' in target.prompt
    assert '「阿莫西林外」' not in target.prompt


# ── F3/F4（2026-10-27 复审）：统一局部子句定位 ─────────────────────

def test_f3_summary_field_between_two_line_clauses_is_kept():
    """F3：汇总字段放在两个行问题中间仍保留为 mixed。"""
    public = _public_lines()
    for question in (
            '第1行复方丹参滴丸、费用总金额以及第2行注射用培美曲塞二钠分别怎么算？',
            '第1行和费用总金额以及第2行分别怎么算？'):
        target = resolve_question_target(public, question)
        assert target.kind == 'mixed', question
        assert 'T_FeeAll' in target.field_codes, question
        assert [line.display_no for line in target.lines] == [1, 2], question
        payload = build_model_input(public, question)
        assert 'T_FeeAll' in {evidence.field_code for evidence in payload.target_evidence}
        answer = explain_decomposition(public, question).answer
        assert '3435.00' in answer and '第 1 行' in answer and '第 2 行' in answer


def test_f3_line_attribute_and_explicit_whole_statement_field_coexist():
    """F3：'第1行医保内，以及整单医保内' 两个目标都保留。"""
    public = _public_lines()
    target = resolve_question_target(public, '第1行医保内金额以及整单医保内金额分别是多少？')
    assert target.kind == 'mixed'
    assert 'T_FeeIn' in target.field_codes
    assert [line.display_no for line in target.lines] == [1]
    assert target.lines[0].attributes == ['observed_in_scope']
    answer = explain_decomposition(public, '第1行医保内金额以及整单医保内金额分别是多少？').answer
    assert '3195.00' in answer and '440.00' in answer


def test_f3_list_marker_with_cover_all_keeps_full_coverage():
    """F3：列表编号+全覆盖仍为 cover_all（不被列表入口提前裁成单行）。"""
    public = _public_lines()
    target = resolve_question_target(public, '请解释全部费用，尤其是1. 复方丹参滴丸')
    assert target.kind == 'cover_all'
    payload = build_model_input(public, '请解释全部费用，尤其是1. 复方丹参滴丸')
    assert [e.display_no for e in payload.line_evidences] == [1, 2, 3, 4, 5, 6]
    answer = explain_decomposition(public, '请解释全部费用，尤其是1. 复方丹参滴丸').answer
    assert '3435.00' in answer and '第 6 行' in answer


def test_f3_named_item_attribute_question_does_not_add_whole_statement():
    """F3：'某药的医保内金额' 只定位该行，不额外加整单医保内目标。"""
    public = _public_lines()
    target = resolve_question_target(public, '复方丹参滴丸的医保内金额是多少？')
    assert target.kind == 'fee_line'
    assert target.display_no == 1
    assert target.attributes == ['observed_in_scope']
    answer = explain_decomposition(public, '复方丹参滴丸的医保内金额是多少？').answer
    assert '440.00' in answer
    assert '3195' not in answer


def test_f3_named_item_with_summary_field_still_mixes():
    """F3 正例：名称+显式汇总字段仍合并为 mixed。"""
    public = _public_lines()
    target = resolve_question_target(public, '费用总金额和复方丹参滴丸的医保内金额各是多少？')
    assert target.kind == 'mixed'
    assert 'T_FeeAll' in target.field_codes
    assert [line.display_no for line in target.lines] == [1]


def test_f4_plain_questions_are_not_item_names():
    """F4：'怎么计算/报销比例/全部纳入医保内' 等正常问句不得被当成项目名拒绝。"""
    public = _public_lines()
    for question in ('第1行是怎么计算的？', '第1行的报销比例是多少？',
                     '第1行为什么全部纳入医保内？', '第1行怎么算'):
        target = resolve_question_target(public, question)
        assert target.kind == 'fee_line', (question, target.kind, target.prompt)
        assert target.display_no == 1, question
        assert '未找到名为' not in (target.prompt or ''), question
        answer = explain_decomposition(public, question).answer
        assert '未找到名为' not in answer, question


def test_f4_repeated_line_with_conflicting_names_is_clarified():
    """F4：同一行号重复出现且名称冲突必须澄清，不能被去重掩盖。"""
    public = _public_lines()
    target = resolve_question_target(
        public, '第1行复方丹参滴丸和第1行注射用培美曲塞二钠分别怎么算？')
    assert target.kind == 'invalid'
    assert '第 1 行' in (target.prompt or '')
    result = explain_decomposition(
        public, '第1行复方丹参滴丸和第1行注射用培美曲塞二钠分别怎么算？')
    assert result.evidence_answer_status == 'none'


def test_f4_repeated_line_with_same_name_is_deduped():
    """F4 正例：同一行号同一名称重复出现只保留一个行目标。"""
    public = _public_lines()
    target = resolve_question_target(
        public, '第1行复方丹参滴丸和第1行复方丹参滴丸分别怎么算？')
    assert target.kind == 'fee_line'
    assert target.display_no == 1


def test_f4_unknown_and_swapped_names_still_rejected():
    """F4 边界：明确未知名、不同行名称互换、越界仍拒绝。"""
    public = _public_lines()
    assert resolve_question_target(
        public, '第1行阿莫西林的医保内外怎么算？').kind == 'invalid'
    assert resolve_question_target(
        public, '第1行注射用培美曲塞二钠和第2行复方丹参滴丸各怎么算？').kind == 'invalid'
    assert resolve_question_target(public, '第9行怎么算？').kind == 'invalid'
