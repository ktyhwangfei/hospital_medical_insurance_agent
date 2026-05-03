from src.config.security_policy.rules import HIGH_RISK_ACTIONS, ROLE_VISIBLE_FIELDS
from src.data_platform.data_access.in_memory import build_sample_store


def test_sample_store_contains_patient_and_settlement_exception_data():
    store = build_sample_store()
    patient = store.get_patient('P001')
    tx = store.get_insurance_transaction('P001', 'E001')

    assert patient.name == '张三'
    assert tx.error_code == 'E-UPLOAD-001'
    assert tx.settlement_status == 'failed'


def test_security_policy_defines_roles_and_high_risk_actions():
    assert ROLE_VISIBLE_FIELDS['cashier'] == {'patient_id', 'encounter_id', 'settlement_status'}
    assert '退费' in HIGH_RISK_ACTIONS
    assert '冲正' in HIGH_RISK_ACTIONS
