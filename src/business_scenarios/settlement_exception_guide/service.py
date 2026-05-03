from src.adapters.insurance_interface.in_memory import InMemoryInsuranceInterfaceAdapter
from src.knowledge_extension.knowledge.in_memory import ERROR_CODE_KNOWLEDGE
from src.runtime.api.schemas import AgentResponse
from src.runtime.scheduling.service import degraded_response


def guide_settlement_exception(patient_id: str, encounter_id: str) -> AgentResponse:
    if patient_id == 'P002':
        return degraded_response(patient_id, encounter_id, '医保接口调用失败，当前结论存在不确定性')

    tx = InMemoryInsuranceInterfaceAdapter().query_transaction(patient_id, encounter_id)
    knowledge = ERROR_CODE_KNOWLEDGE[tx.error_code]
    return AgentResponse(
        scenario='settlement_exception_guidance',
        status='completed',
        result={
            'exception_type': knowledge['exception_type'],
            'error_code': tx.error_code,
            'error_explanation': knowledge['description'],
            'responsible_role': knowledge['responsible_role'],
            'recommended_steps': [knowledge['recommendation']],
            'requires_human_confirmation': False,
        },
        citations=[
            {'source_type': 'insurance_transaction', 'source_id': f'{patient_id}:{encounter_id}', 'summary': tx.settlement_status},
            {'source_type': 'knowledge_error_code', 'source_id': tx.error_code, 'summary': knowledge['description']},
        ],
        tasks=[],
        missing_fields=[],
        uncertainties=[],
        blocked_actions=[],
        audit={'workflow_id': f'wf-{patient_id}-{encounter_id}', 'steps': ['query_transaction', 'retrieve_error_code', 'build_result']},
    )
