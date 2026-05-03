import hashlib

from src.config.security_policy.rules import HIGH_RISK_ACTIONS
from src.runtime.api.schemas import AgentResponse


def detect_blocked_actions(message: str) -> list[str]:
    return [action for action in HIGH_RISK_ACTIONS if action in message]


def build_human_confirmation_response(actions: list[str]) -> AgentResponse:
    actions_key = '-'.join(sorted(actions))
    task_id = f'task-confirm-{hashlib.md5(actions_key.encode()).hexdigest()[:8]}'
    workflow_id = f'wf-high-risk-{task_id}'
    return AgentResponse(
        scenario='high_risk_action_confirmation',
        status='waiting_human_confirmation',
        result={'message': '命中高风险动作，需人工在既有业务系统确认后执行'},
        citations=[{'source_type': 'risk_control_policy', 'source_id': 'HIGH_RISK_ACTIONS', 'summary': '高风险动作黑名单'}],
        tasks=[{'task_id': task_id, 'task_type': 'human_confirmation', 'status': 'pending', 'description': '请人工确认高风险动作', 'workflow_id': workflow_id}],
        missing_fields=[],
        uncertainties=['AI 不会自动执行高风险动作，需人工确认并在既有业务系统处理'],
        blocked_actions=actions,
        audit={'event_type': 'high_risk_action_blocked', 'workflow_id': workflow_id, 'steps': ['detect_high_risk_action', 'create_human_confirmation_task']},
    )
