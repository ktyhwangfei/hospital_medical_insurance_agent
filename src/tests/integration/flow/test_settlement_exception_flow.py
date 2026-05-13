from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def test_settlement_exception_guidance_returns_traceable_recommendation():
    client = TestClient(create_app())
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001',
        'role': 'medical_office',
        'message': '患者 P001 本次医保结算失败，帮我看一下原因',
        'patient_id': 'P001',
        'encounter_id': 'E001',
    })
    assert response.status_code == 200
    body = response.json()
    assert body['scenario'] == 'settlement_exception_guidance'
    assert body['status'] == 'completed'
    
    # 验证知识查询结果在 outputs 中
    outputs = body['result']['outputs']
    assert 'retrieve_error_code' in outputs
    knowledge_output = outputs['retrieve_error_code']['output']
    assert knowledge_output['exception_type'] == '费用上传异常'
    assert knowledge_output['responsible_role'] == '收费员'
