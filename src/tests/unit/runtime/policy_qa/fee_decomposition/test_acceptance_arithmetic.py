"""F5：受控算式的独立 Decimal 核验 + 冻结预期下的错误答案拒绝。

覆盖复审报告列出的五个假通过：
1. `3435＋1＝3435`
2. `3195－1＝3195`
3. `3195×90%＝1597.50`
4. 错误算式加空格（`3195×50% － 2304.50 ＝ 1597.50`）
5. 「暂无计算记录」旁边放其他算式

要求：用有限已注册公式的独立 Decimal 关系判定正确性，不靠数字出现、符号出现或
精确字符串黑名单；0＝0＋0、原单事实、不适用、诚实具体缺证仍按其自身轴分类。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.runtime.policy_qa.fee_decomposition.formula_text import trim_trailing_zeros
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_acceptance_grading import (
    MISSING_EVIDENCE,
    REASON_EXPLAINED,
    TargetRequirement,
    assess_target,
    evaluate_controlled_equations,
)


def _req(**overrides) -> TargetRequirement:
    data = dict(
        key='resident-outpatient-0408.fee_all', label='费用总金额', amount='3435.00',
        kind='explainable', required_values=('3195.00', '240.00'),
        required_tokens=('＝',), required_sources=('居民门诊',))
    data.update(overrides)
    return TargetRequirement(**data)


def test_arithmetic_checks_accept_correct_equation():
    text = '- 费用总金额 3435.00 元；构成：3195.00＋240.00＝3435.00 元；来源：居民门诊待遇参数表。'
    result = evaluate_controlled_equations(text)
    assert result.checked == 1
    assert not result.failures
    assert assess_target(text, _req()).status == REASON_EXPLAINED


@pytest.mark.parametrize('equation', [
    '3435.00＋1.00＝3435.00',
    '3195.00－1.00＝3195.00',
    '3195.00 元×90%＝1597.50 元',
    '取整（3195.00 元×50% － 2304.50 元）＝1597.50 元',
])
def test_arithmetic_checks_reject_wrong_equations(equation):
    text = f'- 费用总金额 3435.00 元；构成：{equation}；来源：居民门诊待遇参数表。'
    result = evaluate_controlled_equations(text)
    assert result.failures, equation
    assert assess_target(text, _req()).status == MISSING_EVIDENCE


def test_max_min_round_chain_is_evaluated_independently():
    """真实封顶公式：较小值/最大值/取整 必须按数值关系复算，而不是只查 token。"""
    correct = ('- 当次门诊大额基金支付金额 1597.50 元；构成：较小值（最大值（取整'
               '（基数 3195.00 元×比例 50%），－交易前已支付 2304.50 元），最大值'
               '（封顶 4500.00 元－已支付 2304.50 元，0））＝1597.50 元；来源：居民门诊待遇参数表。')
    assert not evaluate_controlled_equations(correct).failures
    mutated = correct.replace('×比例 50%', '×比例 90%')
    assert evaluate_controlled_equations(mutated).failures


def test_no_computation_marker_blocks_reason_explained():
    """「暂无计算记录」旁放一个真算式仍不算原因已解释。"""
    text = ('- 费用总金额 3435.00 元；暂无计算记录。另列示3195.00＋240.00＝3435.00 元；'
            '来源：居民门诊待遇参数表。')
    assert assess_target(text, _req()).status == MISSING_EVIDENCE


def test_zero_identity_and_book_facts_still_classified_correctly():
    zero = ('- 大额自付 0.00 元；构成：0.00＋0.00＝0.00 元；来源：本单结算记录。')
    requirement = TargetRequirement(
        'employee-special-567.big_self_pay', '大额自付', '0.00', 'explainable',
        required_values=('0.00',), required_tokens=('＋',), source_record=True)
    assert assess_target(zero, requirement).status == REASON_EXPLAINED
    book = TargetRequirement('employee-outpatient-000008.account_pay', '当次个人帐户支付金额',
                             '2580.00', 'observed_only')
    assert assess_target('- 当次个人帐户支付金额 2580.00 元；按原单记录列示。',
                         book).status == 'book_fact'


def test_explainable_requirement_must_register_composition_and_source():
    with pytest.raises(ValueError):
        TargetRequirement.check({'kind': 'explainable', 'required_values': (),
                                 'required_tokens': (), 'required_sources': (),
                                 'source_record': False})
    with pytest.raises(ValueError):
        TargetRequirement.check({'kind': 'explainable', 'required_values': ('1',),
                                 'required_tokens': ('＝',), 'required_sources': (),
                                 'source_record': False})


def test_source_must_be_from_this_response():
    answer = '- 费用总金额 3435.00 元；构成：3195.00＋240.00＝3435.00 元。'
    requirement = _req(required_sources=('居民门诊待遇参数表',))
    assert assess_target(answer, requirement).status == MISSING_EVIDENCE
    assert assess_target(answer, requirement,
                         citations=('居民门诊待遇参数表',)).status == REASON_EXPLAINED


def test_trim_helper_keeps_precision():
    assert trim_trailing_zeros('3195.000000') == '3195.00'
    assert trim_trailing_zeros('0.0005') == '0.0005'
    assert trim_trailing_zeros('0.125') == '0.125'
    assert Decimal('80') * Decimal('0.125') == Decimal('10.00')


# ── F5：用正式冻结预期拒绝错误正文（不另造更严格的测试专用 requirement）──

def _formal_requirement(case: str, key: str) -> TargetRequirement:
    from src.tests.fixtures.four_chain_acceptance import ACCEPTANCE_EXPECTATIONS
    entry = next(row for row in ACCEPTANCE_EXPECTATIONS[case]['fields']
                 if row['key'].endswith(f'.{key}'))
    return TargetRequirement(
        key=entry['key'], label=entry['label'], amount=entry['amount'], kind=entry['kind'],
        required_tokens=tuple(entry.get('required_tokens') or ()),
        required_values=tuple(entry.get('required_values') or ()),
        required_sources=tuple(entry.get('required_sources') or ()),
        forbidden_tokens=tuple(entry.get('forbidden_tokens') or ()),
        source_record=bool(entry.get('source_record')),
        gap_markers=tuple(entry.get('gap_markers') or ()))


ATTACKS = [
    ('fee_all', '- 费用总金额 3435.00 元；计算构成：3435.00＋1.00＝3435.00 元。'),
    ('fee_in', '- 医疗保险范围内金额 3195.00 元；计算构成：3195.00－1.00＝3195.00 元。'),
    ('big_pay', '- 当次门诊大额基金支付金额 1597.50 元；取整（3195.00 元×90%）＝1597.50 元；'
                '封顶余额 2195.50 元。'),
    ('big_pay', '- 当次门诊大额基金支付金额 1597.50 元；取整（3195.00 元×50% － 2304.50 元）'
                '＝1597.50 元；封顶余额 2195.50 元。'),
    ('fee_all', '- 费用总金额 3435.00 元；暂无计算记录。另列示3435.00＋0＝3435.00 元。'),
]


@pytest.mark.parametrize(('key', 'answer'), ATTACKS)
def test_formal_expectations_reject_reviewed_false_answers(key, answer):
    requirement = _formal_requirement('resident-outpatient-0408', key)
    assessment = assess_target(answer, requirement)
    assert assessment.status == MISSING_EVIDENCE, answer
    assert assessment.delivered is False, answer


def test_formal_expectations_accept_recorded_correct_answers():
    """同一份正式预期对回放中的正确正文必须判为已解释（避免“全部拒绝”式修复）。"""
    import json
    from pathlib import Path
    recording = json.loads((Path('src/tests/fixtures/four_chain_acceptance_recording/recording.json')
                            .read_text(encoding='utf-8')))
    case = 'resident-outpatient-0408'
    for key in ('fee_all', 'fee_in', 'big_pay', 'personal_total', 'self_pay_2'):
        requirement = _formal_requirement(case, key)
        result = recording['cases'][case]['answers'][requirement.key]
        citations = tuple(c.get('title') or '' for c in result.get('citations') or ())
        assert assess_target(result['answer'], requirement, citations).status == REASON_EXPLAINED, key
