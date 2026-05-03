import hashlib

from src.config.security_policy.rules import HIGH_RISK_ACTIONS
from src.runtime.api.schemas import AgentResponse


def detect_blocked_actions(message: str) -> list[str]:
    return [action for action in HIGH_RISK_ACTIONS if action in message]


def build_human_confirmation_response(actions: list[str]) -> AgentResponse:
    actions_key = '-'.join(sorted(actions))
    task_id = f'task-confirm-{hashlib.md5(actions_key.encode()).hexdigest()[:8]}'
    return AgentResponse(
        scenario='high_risk_action_confirmation',
        status='waiting_human_confirmation',
        result={},
        citations=[],
        tasks=[{'task_id': task_id, 'task_type': 'human_confirmation', 'status': 'pending', 'description': '请人工确认高风险动作'}],
        missing_fields=[],
        uncertainties=[],
        blocked_actions=actions,
        audit={'workflow_id': f'wf-high-risk-{task_id}', 'steps': ['detect_high_risk_action', 'create_human_confirmation_task']},
    )