from src.runtime.langgraph.base_state import BaseAgentState
from src.runtime.langgraph.settlement_state import SettlementState
from src.runtime.langgraph.pre_discharge_state import PreDischargeState


def test_base_agent_state_has_required_fields():
    state = BaseAgentState(
        intent='test',
        role='cashier',
        messages=[],
        citations=[],
        uncertainties=[],
        requires_confirmation=False,
        workflow_id='wf1',
    )
    assert state['intent'] == 'test'
    assert state['role'] == 'cashier'
    assert state['messages'] == []
    assert state['citations'] == []
    assert state['uncertainties'] == []
    assert state['requires_confirmation'] is False
    assert state['workflow_id'] == 'wf1'


def test_settlement_state_has_settlement_fields():
    state = SettlementState(
        intent='settlement',
        role='cashier',
        messages=[],
        citations=[],
        uncertainties=[],
        requires_confirmation=False,
        workflow_id='wf1',
        claim_detail={'amount': 100.0},
        error_code='ERR001',
        error_detail={'source': 'insurance'},
        recommendation='请核对费用明细',
        blocked_actions=['refund'],
    )
    keys = set(state.keys())
    assert 'claim_detail' in keys
    assert 'error_code' in keys
    assert 'error_detail' in keys
    assert 'recommendation' in keys
    assert 'blocked_actions' in keys
    assert state['claim_detail'] == {'amount': 100.0}
    assert state['error_code'] == 'ERR001'
    assert state['recommendation'] == '请核对费用明细'


def test_settlement_state_inherits_base_fields():
    state = SettlementState(
        intent='settlement',
        role='cashier',
        messages=['hello'],
        citations=['src'],
        uncertainties=['可能不准确'],
        requires_confirmation=False,
        workflow_id='wf-settle-1',
        claim_detail={},
        error_code='',
        error_detail={},
        recommendation='',
        blocked_actions=[],
    )
    assert state['intent'] == 'settlement'
    assert state['role'] == 'cashier'
    assert state['messages'] == ['hello']
    assert state['citations'] == ['src']
    assert state['uncertainties'] == ['可能不准确']
    assert state['requires_confirmation'] is False
    assert state['workflow_id'] == 'wf-settle-1'


def test_pre_discharge_state_has_qc_fields():
    state = PreDischargeState(
        intent='qc',
        role='doctor',
        messages=[],
        citations=[],
        uncertainties=[],
        requires_confirmation=False,
        workflow_id='wf-qc-1',
        patient_summary={'diagnosis': '肺炎'},
        quality_issues=[{'issue': '病案编码不一致'}],
        rule_results=[{'rule': 'DRG_LOSS_RISK', 'passed': False}],
        qc_recommendation='建议复核主要诊断',
    )
    keys = set(state.keys())
    assert 'patient_summary' in keys
    assert 'quality_issues' in keys
    assert 'rule_results' in keys
    assert 'qc_recommendation' in keys
    assert state['patient_summary'] == {'diagnosis': '肺炎'}
    assert state['quality_issues'] == [{'issue': '病案编码不一致'}]
    assert state['rule_results'] == [{'rule': 'DRG_LOSS_RISK', 'passed': False}]
    assert state['qc_recommendation'] == '建议复核主要诊断'


def test_pre_discharge_state_inherits_base_fields():
    state = PreDischargeState(
        intent='pre_discharge_qc',
        role='doctor',
        messages=['start'],
        citations=[],
        uncertainties=[],
        requires_confirmation=True,
        workflow_id='wf-qc-99',
        patient_summary={},
        quality_issues=[],
        rule_results=[],
        qc_recommendation='',
    )
    assert state['intent'] == 'pre_discharge_qc'
    assert state['role'] == 'doctor'
    assert state['messages'] == ['start']
    assert state['requires_confirmation'] is True
    assert state['workflow_id'] == 'wf-qc-99'


def test_settlement_state_is_typed_dict():
    s = SettlementState(
        intent='settlement',
        role='cashier',
        messages=[],
        citations=[],
        uncertainties=[],
        requires_confirmation=False,
        workflow_id='wf1',
        claim_detail={},
        error_code='',
        error_detail={},
        recommendation='',
        blocked_actions=[],
    )
    assert isinstance(s, dict)
    assert hasattr(s, 'keys')


def test_pre_discharge_state_is_typed_dict():
    s = PreDischargeState(
        intent='qc',
        role='doctor',
        messages=[],
        citations=[],
        uncertainties=[],
        requires_confirmation=False,
        workflow_id='wf1',
        patient_summary={},
        quality_issues=[],
        rule_results=[],
        qc_recommendation='',
    )
    assert isinstance(s, dict)
    assert hasattr(s, 'keys')


def test_settlement_state_keys_contains_all_expected():
    s = SettlementState(
        intent='a',
        role='b',
        messages=[],
        citations=[],
        uncertainties=[],
        requires_confirmation=False,
        workflow_id='c',
        claim_detail={},
        error_code='',
        error_detail={},
        recommendation='',
        blocked_actions=[],
    )
    expected_keys = {
        'intent', 'role', 'messages', 'citations', 'uncertainties',
        'requires_confirmation', 'workflow_id',
        'claim_detail', 'error_code', 'error_detail', 'recommendation',
        'blocked_actions',
    }
    assert set(s.keys()) == expected_keys


def test_pre_discharge_state_keys_contains_all_expected():
    s = PreDischargeState(
        intent='a',
        role='b',
        messages=[],
        citations=[],
        uncertainties=[],
        requires_confirmation=False,
        workflow_id='c',
        patient_summary={},
        quality_issues=[],
        rule_results=[],
        qc_recommendation='',
    )
    expected_keys = {
        'intent', 'role', 'messages', 'citations', 'uncertainties',
        'requires_confirmation', 'workflow_id',
        'patient_summary', 'quality_issues', 'rule_results',
        'qc_recommendation',
    }
    assert set(s.keys()) == expected_keys
