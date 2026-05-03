from src.runtime.api.schemas import AgentResponse


def degraded_response(patient_id: str, encounter_id: str, reason: str) -> AgentResponse:
    workflow_id = f'wf-{patient_id}-{encounter_id}'
    return AgentResponse(
        scenario='settlement_exception_guidance',
        status='degraded',
        result={},
        citations=[{'source_type': 'adapter_failure', 'source_id': f'{patient_id}:{encounter_id}', 'summary': reason}],
        tasks=[],
        missing_fields=[],
        uncertainties=[reason],
        blocked_actions=[],
        audit={'event_type': 'degraded_response_returned', 'workflow_id': workflow_id, 'steps': ['query_transaction_failed', 'return_degraded_result']},
    )
