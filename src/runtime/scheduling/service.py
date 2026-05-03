from src.runtime.api.schemas import AgentResponse


def degraded_response(patient_id: str, encounter_id: str, reason: str) -> AgentResponse:
    return AgentResponse(
        scenario='settlement_exception_guidance',
        status='degraded',
        result={},
        citations=[],
        tasks=[],
        missing_fields=[],
        uncertainties=[reason],
        blocked_actions=[],
        audit={'workflow_id': f'wf-{patient_id}-{encounter_id}', 'steps': ['query_transaction_failed', 'return_degraded_result']},
    )
