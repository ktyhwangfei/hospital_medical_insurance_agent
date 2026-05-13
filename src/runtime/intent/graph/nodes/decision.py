from src.runtime.intent.graph.state import IntentGraphState


def decision(state: IntentGraphState) -> str:
    status = state.get('status', 'unknown')
    if status == 'needs_clarification':
        return 'clarify'
    if status == 'unknown':
        return 'unknown'
    if status == 'fallback_keyword':
        return 'routed'
    return 'routed'
