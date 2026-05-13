import hashlib
import logging
import re

from src.config.security_policy.rules import HIGH_RISK_ACTIONS
from src.runtime.api.schemas import AgentResponse
from src.runtime.task_closure.service import create_task

logger = logging.getLogger(__name__)


def _load_db_rules() -> list[dict]:
    """从数据库加载风控规则（完整字典），失败时返回空列表"""
    try:
        from src.security.risk_control.storage.postgres import PostgresRiskControlStorage
        store = PostgresRiskControlStorage()
        return store.list_rules()
    except Exception as e:
        logger.warning(f"Failed to load risk control rules from DB, using hardcoded fallback: {e}")
        return []


def detect_blocked_actions(message: str) -> list[tuple[str, str]]:
    """检测消息中的高风险动作，返回 (action_pattern, rule_id) 列表

    DB规则优先查询 risk_control_rules 表；DB不可用时回退到硬编码 HIGH_RISK_ACTIONS 兜底。
    """
    db_rules = _load_db_rules()
    if db_rules:
        # L0: DB规则优先
        actions: list[tuple[str, str]] = []
        for rule in db_rules:
            if not rule.get('enabled', True):
                continue
            pattern = rule.get('action_pattern', '')
            rule_id = rule.get('rule_id', 'unknown')
            if pattern and re.search(pattern, message):
                actions.append((pattern, rule_id))
        return actions
    # L1: DB不可用时回退到硬编码规则
    return [(a, 'hardcoded') for a in HIGH_RISK_ACTIONS if a in message]


def build_human_confirmation_response(actions: list[tuple[str, str]] | list[str]) -> AgentResponse:
    """构建高风险动作的人工确认响应。

    Args:
        actions: (action_pattern, rule_id) 元组列表，或仅 action_pattern 的字符串列表（向后兼容）。
                 rule_id 为 'hardcoded' 表示来自硬编码兜底规则。
    """
    # 兼容 list[str] 格式（旧测试代码）: 转为 list[tuple[str, str]]
    if actions and isinstance(actions[0], str):
        _str_actions: list[str] = actions  # noqa: F841
        action_patterns = _str_actions
        rule_ids = ['hardcoded'] * len(_str_actions)
        _tuples: list[tuple[str, str]] = list(zip(action_patterns, rule_ids))
    else:
        _tuples = actions  # type: ignore[assignment]
        action_patterns = [a for a, _ in _tuples]
        rule_ids = [r for _, r in _tuples]

    actions_key = '-'.join(sorted(action_patterns))
    task_id = f'task-confirm-{hashlib.md5(actions_key.encode()).hexdigest()[:8]}'
    workflow_id = f'wf-high-risk-{task_id}'
    # 写入风控事件（每条匹配规则记录一条事件）
    try:
        from src.security.risk_control.storage.postgres import PostgresRiskControlStorage
        store = PostgresRiskControlStorage()
        for action_pattern, rule_id in _tuples:
            store.record_event({
                'rule_id': rule_id,
                'event_type': 'blocked',
                'user_id': None,
                'patient_id': None,
                'encounter_id': None,
                'action_pattern': action_pattern,
                'risk_level': 'HIGH',
                'blocked': True,
                'reason': None,
                'result': 'blocked',
                'workflow_id': workflow_id,
                'context': {},
            })
    except Exception as e:
        logger.warning(f"Failed to record risk control event: {e}")
    citation_rules = ', '.join(sorted(set(rule_ids)))
    return AgentResponse(
        scenario='high_risk_action_confirmation',
        status='waiting_human_confirmation',
        result={'message': '命中高风险动作，需人工在既有业务系统确认后执行'},
        citations=[{'source_type': 'risk_control_policy', 'source_id': citation_rules, 'summary': '高风险动作黑名单'}],
        tasks=[create_task(task_id, 'human_confirmation', '请人工确认高风险动作', '医保办', workflow_id)],
        missing_fields=[],
        uncertainties=['AI 不会自动执行高风险动作，需人工确认并在既有业务系统处理'],
        blocked_actions=action_patterns,
        audit={'event_type': 'high_risk_action_blocked', 'workflow_id': workflow_id, 'steps': ['detect_high_risk_action', 'create_human_confirmation_task']},
    )
