from src.adapters.drg_dip.in_memory import InMemoryDrgDipAdapter
from src.adapters.medical_record.in_memory import InMemoryMedicalRecordAdapter
from src.adapters.pre_audit.in_memory import InMemoryPreAuditAdapter
from src.runtime.api.schemas import AgentResponse


def run_pre_discharge_qc(patient_id: str, encounter_id: str) -> AgentResponse:
    pre_audit = InMemoryPreAuditAdapter().query_audit_result(patient_id, encounter_id)
    drg = InMemoryDrgDipAdapter().query_group_result(patient_id, encounter_id)
    mr = InMemoryMedicalRecordAdapter().query_homepage(patient_id, encounter_id)

    risks = [
        {'risk_type': pre_audit.data['risk'], 'risk_level': pre_audit.data.get('risk_level', 'high'), 'responsible_role': '医保办', 'recommendation': '复核限制用药规则命中原因'},
        {'risk_type': drg.data['risk'], 'risk_level': drg.data.get('risk_level', 'medium'), 'responsible_role': '科主任', 'recommendation': '关注病组盈亏和费用结构'},
        {'risk_type': mr.data['risk'], 'risk_level': mr.data.get('risk_level', 'medium'), 'responsible_role': '病案室', 'recommendation': '复核主要诊断与手术编码'},
    ]
    tasks = [
        {'task_id': f'task-qc-{idx}', 'task_type': 'rectification', 'status': 'pending', 'responsible_role': risk['responsible_role'], 'description': risk['recommendation']}
        for idx, risk in enumerate(risks, start=1)
    ]
    return AgentResponse(
        scenario='pre_discharge_quality_control',
        status='completed',
        result={'risks': risks},
        citations=[
            {'source_type': pre_audit.source_system, 'source_id': pre_audit.source_record_id, 'summary': pre_audit.data['risk']},
            {'source_type': drg.source_system, 'source_id': drg.source_record_id, 'summary': drg.data['risk']},
            {'source_type': mr.source_system, 'source_id': mr.source_record_id, 'summary': mr.data['risk']},
        ],
        tasks=tasks,
        missing_fields=[],
        uncertainties=[],
        blocked_actions=[],
        audit={'workflow_id': f'wf-qc-{patient_id}-{encounter_id}', 'steps': ['query_pre_audit', 'query_drg_dip', 'query_medical_record', 'create_tasks']},
    )
