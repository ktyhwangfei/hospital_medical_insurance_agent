from src.adapters.drg_dip.in_memory import InMemoryDrgDipAdapter
from src.adapters.medical_record.in_memory import InMemoryMedicalRecordAdapter
from src.adapters.pre_audit.in_memory import InMemoryPreAuditAdapter
from src.knowledge_extension.service import KnowledgeEnhancementRequest, build_default_knowledge_extension_service
from src.runtime.api.schemas import AgentResponse


def enhance_qc_knowledge(patient_id: str | None) -> dict:
    service = build_default_knowledge_extension_service()
    result = service.enhance(KnowledgeEnhancementRequest(message="出院前联合质控 DRG DIP 病案风险", scenario="pre_discharge_qc", role="doctor", patient_id=patient_id, rule_code="DRG_LOSS_RISK"))
    return result.to_agent_payload()


def run_pre_discharge_qc(patient_id: str, encounter_id: str) -> AgentResponse:
    pre_audit = InMemoryPreAuditAdapter().query_audit_result(patient_id, encounter_id)
    drg = InMemoryDrgDipAdapter().query_group_result(patient_id, encounter_id)
    mr = InMemoryMedicalRecordAdapter().query_homepage(patient_id, encounter_id)

    risks = [
        {'risk_type': pre_audit['risk'], 'risk_level': pre_audit.get('risk_level', 'high'), 'responsible_role': '医保办', 'recommendation': '复核限制用药规则命中原因'},
        {'risk_type': drg['risk'], 'risk_level': drg.get('risk_level', 'medium'), 'responsible_role': '科主任', 'recommendation': '关注病组盈亏和费用结构'},
        {'risk_type': mr['risk'], 'risk_level': mr.get('risk_level', 'medium'), 'responsible_role': '病案室', 'recommendation': '复核主要诊断与手术编码'},
    ]
    tasks = [
        {'task_id': f'task-qc-{idx}', 'task_type': 'rectification', 'status': 'pending', 'responsible_role': risk['responsible_role'], 'description': risk['recommendation']}
        for idx, risk in enumerate(risks, start=1)
    ]
    response = AgentResponse(
        scenario='pre_discharge_quality_control',
        status='completed',
        result={'risks': risks},
        citations=[
            {'source_type': 'pre_audit', 'source_id': f'{patient_id}:{encounter_id}', 'summary': pre_audit['risk']},
            {'source_type': 'drg_dip', 'source_id': f'{patient_id}:{encounter_id}', 'summary': drg['risk']},
            {'source_type': 'medical_record', 'source_id': f'{patient_id}:{encounter_id}', 'summary': mr['risk']},
        ],
        tasks=tasks,
        missing_fields=[],
        uncertainties=[],
        blocked_actions=[],
        audit={'workflow_id': f'wf-qc-{patient_id}-{encounter_id}', 'steps': ['query_pre_audit', 'query_drg_dip', 'query_medical_record', 'create_tasks']},
    )
    knowledge = enhance_qc_knowledge(patient_id)
    response.citations.extend(knowledge["citations"])
    response.uncertainties.extend(knowledge["uncertainties"])
    response.audit["knowledge_extension"] = knowledge["audit_events"]
    return response
