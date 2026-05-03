from unittest.mock import patch

from src.adapters.base.models import AdapterCallResult, AdapterCallStatus
from src.runtime.api.schemas import (
    AgentResponse,
    ChatRequest,
    PatientContextResponse,
    TaskConfirmRequest,
    TaskConfirmResponse,
    TaskStatusResponse,
    WorkflowStatusResponse,
)


def test_chat_returns_agent_response_instance():
    from src.runtime.api.routes import chat

    request = ChatRequest(
        user_id='u1',
        role='medical_office',
        message='患者 P001 医保结算失败',
        patient_id='P001',
        encounter_id='E001',
    )
    result = chat(request)
    assert isinstance(result, AgentResponse)


def test_chat_missing_context_returns_agent_response():
    from src.runtime.api.routes import chat

    request = ChatRequest(
        user_id='u1',
        role='cashier',
        message='医保结算失败了，帮我看看',
    )
    result = chat(request)
    assert isinstance(result, AgentResponse)
    assert result.status == 'needs_clarification'
    assert result.missing_fields == ['patient_id', 'encounter_id']


def test_patient_context_returns_typed_model():
    from src.runtime.api.routes import patient_context

    result = patient_context(patient_id='P001', encounter_id='E001', user_id='u1', role='cashier')
    assert isinstance(result, PatientContextResponse)
    assert result.settlement_status == 'failed'


def test_workflow_status_returns_typed_model():
    from src.runtime.api.routes import workflow_status

    result = workflow_status(workflow_id='wf-001')
    assert isinstance(result, WorkflowStatusResponse)


def test_task_status_returns_typed_model():
    from src.runtime.api.routes import task_status

    result = task_status(task_id='task-001')
    assert isinstance(result, TaskStatusResponse)


def test_confirm_task_returns_typed_model():
    from src.runtime.api.routes import confirm_task

    request = TaskConfirmRequest(task_id='task-001', action='confirm', user_id='u1')
    result = confirm_task(request)
    assert isinstance(result, TaskConfirmResponse)
    assert result.status == 'confirmed'


def test_pre_discharge_qc_calls_adapters_not_hardcode():
    with (
        patch('src.business_scenarios.pre_discharge_joint_qc.service.InMemoryPreAuditAdapter') as mock_pre_audit,
        patch('src.business_scenarios.pre_discharge_joint_qc.service.InMemoryDrgDipAdapter') as mock_drg,
        patch('src.business_scenarios.pre_discharge_joint_qc.service.InMemoryMedicalRecordAdapter') as mock_mr,
    ):
        mock_pre_audit.return_value.query_audit_result.return_value = AdapterCallResult(
            status=AdapterCallStatus.SUCCESS,
            source_system='pre_audit',
            source_record_id='P001:E001',
            capability='query_audit_result',
            data={'risk': 'test_audit_risk', 'risk_level': 'high', 'patient_id': 'P001', 'encounter_id': 'E001'},
        )
        mock_drg.return_value.query_group_result.return_value = AdapterCallResult(
            status=AdapterCallStatus.SUCCESS,
            source_system='drg_dip',
            source_record_id='P001:E001',
            capability='query_group_result',
            data={'risk': 'test_drg_risk', 'risk_level': 'medium', 'patient_id': 'P001', 'encounter_id': 'E001'},
        )
        mock_mr.return_value.query_homepage.return_value = AdapterCallResult(
            status=AdapterCallStatus.SUCCESS,
            source_system='medical_record',
            source_record_id='P001:E001',
            capability='query_homepage',
            data={'risk': 'test_mr_risk', 'risk_level': 'low', 'patient_id': 'P001', 'encounter_id': 'E001'},
        )

        from src.business_scenarios.pre_discharge_joint_qc.service import run_pre_discharge_qc

        result = run_pre_discharge_qc('P001', 'E001')

        mock_pre_audit.return_value.query_audit_result.assert_called_once_with('P001', 'E001')
        mock_drg.return_value.query_group_result.assert_called_once_with('P001', 'E001')
        mock_mr.return_value.query_homepage.assert_called_once_with('P001', 'E001')
        assert result.result['risks'][0]['risk_type'] == 'test_audit_risk'


def test_human_confirmation_task_id_is_deterministic_and_unique():
    from src.security.risk_control.service import build_human_confirmation_response

    r1 = build_human_confirmation_response(['退费'])
    r2 = build_human_confirmation_response(['退费', '冲正'])
    r3 = build_human_confirmation_response(['退费'])

    assert r1.tasks[0]['task_id'] == r3.tasks[0]['task_id']
    assert r1.tasks[0]['task_id'] != r2.tasks[0]['task_id']
    assert r1.tasks[0]['task_id'].startswith('task-confirm-')
    assert len(r2.tasks) >= 1


def test_human_confirmation_returns_agent_response():
    from src.security.risk_control.service import build_human_confirmation_response

    result = build_human_confirmation_response(['退费'])
    assert isinstance(result, AgentResponse)


def test_guide_settlement_exception_returns_agent_response():
    from src.business_scenarios.settlement_exception_guide.service import guide_settlement_exception

    result = guide_settlement_exception('P001', 'E001')
    assert isinstance(result, AgentResponse)


def test_degraded_response_returns_agent_response():
    from src.runtime.scheduling.service import degraded_response

    result = degraded_response('P002', 'E002', '医保接口调用失败')
    assert isinstance(result, AgentResponse)
    assert result.status == 'degraded'


def test_run_pre_discharge_qc_returns_agent_response():
    from src.business_scenarios.pre_discharge_joint_qc.service import run_pre_discharge_qc

    result = run_pre_discharge_qc('P001', 'E001')
    assert isinstance(result, AgentResponse)
