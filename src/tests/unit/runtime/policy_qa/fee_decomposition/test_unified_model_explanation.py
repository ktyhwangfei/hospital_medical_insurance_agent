"""统一费用解释：表达由提示词维护，事实校验覆盖所有目标类型。"""
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.runtime.policy_qa.fee_decomposition import model_explanation as explanation
from src.runtime.policy_qa.fee_decomposition.answer_validation import equation_issues
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_model_explanation import (
    _public_0408, _public_special_567, _public_special_688,
    _public_with_duplicate_named_lines, _precision_result, _public_from,
)


def _model(monkeypatch, answer):
    calls = []

    def generate(self, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content=answer(len(calls)) if callable(answer) else answer)

    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate', generate)
    monkeypatch.setenv('FEE_EXPLANATION_MODE', 'structured')
    return calls


@pytest.mark.parametrize(('factory', 'question', 'answer'), [
    (_public_0408, '现金支付是多少', '现金支付 1837.50 元，是个人负担的支付方式。'),
    (_public_0408, '账户支付是多少', '账户支付 0.00 元，本笔通过现金支付个人负担。'),
    (_public_special_567, '统筹基金支付是多少', '统筹基金支付 4277.00 元。'),
    (_public_special_688, '大病支付是多少', '大病支付 226.96 元，其中医保内 181.53 元、医保外 45.43 元。'),
    (_public_with_duplicate_named_lines, '第6行人工晶体多少钱',
     '第6行人工晶体的本行费用为 1935.00 元。'),
])
def test_fields_and_lines_use_the_same_model_entry(monkeypatch, factory, question, answer):
    calls = _model(monkeypatch, answer)
    result = explanation.explain_decomposition(factory(), question)
    assert result.used_model and result.model_attempted
    assert result.answer == answer
    assert len(calls) == 1


@pytest.mark.parametrize('answer', [
    '退役医疗费为 0.00 元，该渠道未触发。',
    '现金支付 1597.50 元。',
])
def test_wrong_target_or_amount_falls_back_with_reason(monkeypatch, answer):
    calls = _model(monkeypatch, answer)
    result = explanation.explain_decomposition(_public_0408(), '现金支付是多少')
    assert not result.used_model
    assert result.model_attempted and result.fallback_reason == 'validation_rejected'
    assert '1837.50' in result.answer
    assert len(calls) == 2


@pytest.mark.parametrize('equation', [
    '4277.00＝4277.00＋4277.00',
    '4277.00 = 4277.00 - 4277.00',
    '4277.00＝取整（4277.00×60%）',
])
def test_known_numbers_do_not_allow_false_equations(monkeypatch, equation):
    _model(monkeypatch, f'统筹基金支付 4277.00 元，{equation}。')
    result = explanation.explain_decomposition(_public_special_567(), '统筹基金支付怎么算')
    assert not result.used_model
    assert result.fallback_reason == 'validation_rejected'


def test_repair_uses_the_same_facts_and_stops_after_success(monkeypatch):
    correct = '现金支付 1837.50 元，是本单个人负担的支付方式。'
    calls = _model(monkeypatch, lambda count: '退役医疗费为 0.00 元。' if count == 1 else correct)
    result = explanation.explain_decomposition(_public_0408(), '现金支付是多少')
    assert result.used_model and result.answer == correct
    assert result.fallback_reason is None
    assert len(calls) == 2
    assert calls[0]['messages'][1] == calls[1]['messages'][1]


def test_prompt_is_reloaded_and_adjust_uses_the_same_pipeline(monkeypatch, tmp_path):
    prompt = tmp_path / 'explanation_prompt.yaml'
    monkeypatch.setattr(explanation, '_PROMPT_PATH', prompt)
    calls = _model(monkeypatch, '现金支付 1837.50 元。')
    for index, mode in enumerate(('structured', 'adjust')):
        prompt.write_text(f'system_prompt: 提示词版本{index}\nrepair_prompt: 请按资料纠正错误。\n', encoding='utf-8')
        monkeypatch.setenv('FEE_EXPLANATION_MODE', mode)
        assert explanation.explain_decomposition(_public_0408(), '现金支付是多少').used_model
        assert calls[-1]['messages'][0].content == f'提示词版本{index}'
        assert json.loads(calls[-1]['messages'][1].content)['target_evidence']


def test_model_gets_evidence_without_precomposed_answer(monkeypatch):
    calls = _model(monkeypatch, '本次大额支付 1597.50 元，作用基数为 3195.00 元，比例为 50%。')
    result = explanation.explain_decomposition(_public_0408(), '大额支付怎么算')
    assert result.used_model
    payload = json.loads(calls[0]['messages'][1].content)
    assert 'sentence' not in payload['target_evidence'][0]
    assert payload['decomposition']['calculations']
    assert payload['decomposition']['rule_choices']
    assert 'template_explanations' not in payload['decomposition']


def test_unverified_candidate_calculations_are_not_sent_as_explanation(monkeypatch):
    data = _public_from(_precision_result(field_observed='60.00', field_calculated='50.00',
                                         field_status='mismatched'))
    calls = _model(monkeypatch, '费用总金额 60.00 元，本项缺少已核对的计算依据。')
    result = explanation.explain_decomposition(data, '费用总金额是多少')
    assert result.used_model
    payload = json.loads(calls[0]['messages'][1].content)
    assert payload['decomposition']['fields'][0]['calculated_amount'] is None
    assert not payload['decomposition'].get('calculations')


def test_governance_notes_are_not_copied_into_model_context(monkeypatch):
    calls = _model(monkeypatch, '大额支付 1597.50 元。')
    assert explanation.explain_decomposition(_public_0408(), '大额支付是多少').used_model
    payload = calls[0]['messages'][1].content
    assert '跨院' not in payload
    assert '取整规则尚待确认' not in payload


def test_valid_prose_is_not_deleted_by_display_keywords(monkeypatch):
    answer = '大额支付 1597.50 元，本次采用 50% 的比例，作用基数为 3195.00 元。'
    _model(monkeypatch, answer)
    result = explanation.explain_decomposition(_public_0408(), '大额支付怎么算')
    assert result.used_model and result.answer == answer


def test_invalid_mode_does_not_silently_disable_model(monkeypatch):
    calls = _model(monkeypatch, '现金支付 1837.50 元。')
    monkeypatch.setenv('FEE_EXPLANATION_MODE', 'structrued')
    result = explanation.explain_decomposition(_public_0408(), '现金支付是多少')
    assert result.used_model and len(calls) == 1


def test_gateway_error_is_distinguishable_from_no_model_attempt(monkeypatch):
    def fail(_count):
        raise RuntimeError('private provider error')

    _model(monkeypatch, fail)
    result = explanation.explain_decomposition(_public_0408(), '现金支付是多少')
    assert result.model_attempted and not result.used_model
    assert result.fallback_reason == 'model_error'
    assert 'private' not in result.answer


def test_currency_grouping_and_plain_equations_are_accepted(monkeypatch):
    answer = '现金支付 1,837.50 元。'
    _model(monkeypatch, answer)
    result = explanation.explain_decomposition(_public_0408(), '现金支付是多少')
    assert result.used_model and result.answer == answer


@pytest.mark.parametrize(('answer', 'accepted'), [
    ('现金支付 1837.50 元，账户支付 0.00 元。', True),
    ('现金支付 1837.50 元。', False),
])
def test_multiple_fields_are_checked_together(monkeypatch, answer, accepted):
    _model(monkeypatch, answer)
    result = explanation.explain_decomposition(_public_0408(), '现金支付和账户支付各是多少')
    assert result.used_model is accepted


def test_mixed_summary_and_line_use_one_model_answer(monkeypatch):
    answer = '费用总金额 3435.00 元。第6行人工晶体的本行费用为 1935.00 元。'
    calls = _model(monkeypatch, answer)
    result = explanation.explain_decomposition(
        _public_with_duplicate_named_lines(), '费用总金额是多少，第6行人工晶体多少钱')
    assert result.used_model and result.answer == answer
    assert len(calls) == 1


@pytest.mark.parametrize('text', [
    '本行费用＝80×0.125＝10.00元。',
    '大病医保内支付＝取整（279.27×65%）＝181.53元。',
    '医保外支付＝69.90×65%＝45.43元，按本单结算记录采用。',
    '大额支付＝min(max(round(3195×50%),-2304.50),2195.50)＝1597.50元。',
    '现金支付＝1837.50元。',
    '封顶余额＝4500 − 2304.50＝2195.50元。',
    '首段比例＝0.60＋0.05＝0.65，第二段比例＝0.70＋0.05＝0.75。',
    '大病支付＝181.53＋45.43＝226.96元，两个分桶相加。',
])
def test_equation_validation_preserves_precision_and_supported_operations(text):
    assert equation_issues(text) == []


@pytest.mark.parametrize('text', [
    '结果＝1/0＝0。', '结果＝2**100＝2。',
    '支付4277.00元＝4277.00＋4277.00元，按本单记录。',
    '结果＝__import__("os").getcwd()＝1。',
])
def test_equation_validation_rejects_unsupported_expressions(text):
    assert equation_issues(text)


def test_bucket_label_is_not_bound_to_the_whole_field_amount():
    text = '医保内救助＝97.74×100%＝97.74元；医保外救助＝24.47×100%＝24.47元。'
    assert equation_issues(text, {'救助': Decimal('122.21')}) == []
    assert equation_issues('本次救助＝97.74元。', {'救助': Decimal('122.21')})
