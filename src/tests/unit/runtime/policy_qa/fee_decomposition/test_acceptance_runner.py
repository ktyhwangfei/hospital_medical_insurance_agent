"""F6：验收 runner 自身的失败测试（离线回放，不发真实请求）。

覆盖复审报告的两个变异：
1. 把总览/范围探针全部改成 unavailable → runner 必须非零退出；
2. 面板增加一条未验收费用行 → runner 必须非零退出；
并保留正确回放成功、字段/行集合完整校验的正例。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
RECORDING = ROOT / 'src/tests/fixtures/four_chain_acceptance_recording/recording.json'


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        'four_chain_runner', ROOT / 'scripts/eval/four_chain_acceptance.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _recording(tmp_path: Path) -> Path:
    target = tmp_path / 'recording'
    target.mkdir(parents=True, exist_ok=True)
    (target / 'recording.json').write_text(RECORDING.read_text(encoding='utf-8'), encoding='utf-8')
    return target


def _mutate(recording: Path, mutate) -> Path:
    path = recording / 'recording.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    mutate(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return recording


def _run(recording: Path, out: Path) -> tuple[int, str]:
    runner = _load_runner()
    code = runner.main(['--replay', str(recording), '--out', str(out)])
    return code, (out / 'summary.json').read_text(encoding='utf-8')


def test_replay_accepts_recorded_correct_responses(tmp_path):
    """正确回放必须成功（防止把 runner 改成一律失败）。"""
    code, summary = _run(_recording(tmp_path), tmp_path / 'out')
    data = json.loads(summary)
    assert code == 0, data['problems']
    assert data['problems'] == []
    assert data['summary']['resident-outpatient-0408']['visible_amounts'] == 19


def test_replay_rejects_unavailable_probes(tmp_path):
    """探针全部 unavailable/空正文：runner 必须非零退出并点名探针。"""
    recording = _recording(tmp_path)

    def degrade(data):
        for case in data['cases'].values():
            for probe in case['probes'].values():
                probe['answer'] = '没有可交付依据'
                probe['answer_status'] = 'unavailable'
                probe['calculation_checked'] = False

    _mutate(recording, degrade)
    code, summary = _run(recording, tmp_path / 'out')
    problems = json.loads(summary)['problems']
    assert code == 1
    assert any('.field_with_item' in problem for problem in problems)
    assert any('.line_and_whole_field' in problem for problem in problems)


def test_replay_rejects_extra_unverified_fee_line(tmp_path):
    """面板多一条未验收费用行：集合校验必须失败。"""
    recording = _recording(tmp_path)

    def add_line(data):
        panel = data['cases']['resident-outpatient-0408']['panel']
        panel['fee_items'].append({
            'line_id': 'new-unverified-line', 'item_name': '未验收项目',
            'total_fee': '1.00', 'observed_in_scope': '1.00'})

    _mutate(recording, add_line)
    code, summary = _run(recording, tmp_path / 'out')
    problems = json.loads(summary)['problems']
    assert code == 1
    assert any('费用行集合/顺序不一致' in problem for problem in problems)


def test_replay_rejects_missing_and_swapped_fee_lines(tmp_path):
    recording = _recording(tmp_path)

    def remove_line(data):
        data['cases']['resident-special-688']['panel']['fee_items'].pop()

    _mutate(recording, remove_line)
    code, summary = _run(recording, tmp_path / 'out')
    assert code == 1
    assert any('费用行集合/顺序不一致' in problem for problem in json.loads(summary)['problems'])

    recording = _recording(tmp_path / 'swap')

    def swap_lines(data):
        items = data['cases']['resident-special-688']['panel']['fee_items']
        items.reverse()

    _mutate(recording, swap_lines)
    code, summary = _run(recording, tmp_path / 'out2')
    assert code == 1
    assert any('费用行集合/顺序不一致' in problem for problem in json.loads(summary)['problems'])


def test_replay_rejects_missing_display_field(tmp_path):
    recording = _recording(tmp_path)

    def remove_field(data):
        fields = data['cases']['employee-special-567']['panel']['settlement_facts'][
            'display_template']['fields']
        fields.pop(0)

    _mutate(recording, remove_field)
    code, summary = _run(recording, tmp_path / 'out')
    assert code == 1
    assert any('展示字段集合不一致' in problem for problem in json.loads(summary)['problems'])


def test_probe_questions_use_real_item_names():
    """探针必须是真正的“字段＋项目名”问题，不能拼成“费用总金额和费用总金额”。"""
    runner = _load_runner()
    from src.tests.fixtures.four_chain_acceptance import ACCEPTANCE_EXPECTATIONS
    for case, expectation in ACCEPTANCE_EXPECTATIONS.items():
        questions = runner.probe_questions(expectation)
        first = expectation['lines'][0]['item_name']
        assert first in questions['field_with_item'], case
        assert '费用总金额' in questions['field_with_item'], case
        assert first in questions['cover_all_with_item'], case


def test_replay_rejects_wrong_equations_in_official_recording(tmp_path):
    """把真实回放中的正确正文替换为复审列出的错误算式：runner 必须非零退出。"""
    recording = _recording(tmp_path)
    attacks = {
        'resident-outpatient-0408.fee_all':
            '- 费用总金额 3435.00 元；计算构成：3435.00＋1.00＝3435.00 元。',
        'resident-outpatient-0408.fee_in':
            '- 医疗保险范围内金额 3195.00 元；计算构成：3195.00－1.00＝3195.00 元。',
        'resident-outpatient-0408.big_pay':
            '- 当次门诊大额基金支付金额 1597.50 元；取整（3195.00 元×90%）＝1597.50 元；'
            '封顶余额 2195.50 元。',
    }

    def replace_answers(data):
        answers = data['cases']['resident-outpatient-0408']['answers']
        for key, answer in attacks.items():
            answers[key]['answer'] = answer
            answers[key]['answer_status'] = 'partial'

    _mutate(recording, replace_answers)
    code, summary = _run(recording, tmp_path / 'out')
    problems = json.loads(summary)['problems']
    assert code == 1
    for key in attacks:
        assert any(key in problem for problem in problems), key
