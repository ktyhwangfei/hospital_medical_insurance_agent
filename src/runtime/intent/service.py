import os

from src.runtime.intent.graph.graph import IntentGraph
from src.runtime.intent.models import IntentResult
from src.runtime.intent.parser import parse_intent


def detect_intent(message: str) -> str:
    result = parse_intent(message)
    return result.intent


def parse_intent_v2(
    message: str,
    role: str = '',
    history: list | None = None,
) -> IntentResult:
    graph = IntentGraph()
    return graph.run(message, role=role, history=history)


def detect_intent_smart(
    message: str,
    role: str = '',
    history: list | None = None,
) -> IntentResult:
    v2_enabled = os.environ.get('INTENT_ENGINE_V2_ENABLED', '').lower() in ('1', 'true', 'yes')
    if v2_enabled:
        return parse_intent_v2(message, role=role, history=history)
    return parse_intent(message)
