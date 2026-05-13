from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def test_pre_discharge_quality_control_creates_tasks_with_citations():
    client = TestClient(create_app())
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001', 'role': 'medical_office', 'message': '帮我检查患者 P001 出院前医保风险', 'patient_id': 'P001', 'encounter_id': 'E001'
    })
    body = response.json()
    assert body['scenario'] == 'pre_discharge_quality_control'
    assert body['status'] == 'completed'
    
    # 验证输出包含各个步骤的结果
    outputs = body['result']['outputs']
    assert 'query_orders' in outputs
    assert 'query_insurance_status' in outputs
    assert 'query_pre_audit' in outputs
    assert 'query_drg_dip' in outputs
    assert 'query_medical_record' in outputs
    assert 'retrieve_rule_explanation' in outputs
    assert 'build_risk_list' in outputs
    assert 'create_tasks' in outputs
    
    # 验证步骤都已完成
    for step_name, step_result in outputs.items():
        assert step_result['status'] == 'completed'
