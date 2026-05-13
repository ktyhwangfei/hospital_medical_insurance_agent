from src.runtime.intent.graph.config import IntentGraphConfig
from src.runtime.intent.graph.state import IntentGraphState
from src.runtime.intent.registry import get_intent_by_id


def validation(
    state: IntentGraphState,
    config: IntentGraphConfig | None = None,
) -> dict:
    cfg = config or IntentGraphConfig()
    intent_id = state.get('intent_id', 'unknown')
    confidence = state.get('confidence', 0.0)
    result_status = state.get('status', 'unknown')

    entry = get_intent_by_id(intent_id)
    if entry is None:
        return {
            'intent_id': 'unknown',
            'confidence': 0.0,
            'missing_fields': [],
            'clarification_needed': False,
            'status': 'unknown',
        }

    missing = _check_required_entities(state, entry)
    needs_clarification = False
    question = None

    if confidence < cfg.confidence_threshold and cfg.enable_clarification:
        needs_clarification = True
        question = _build_clarification_question(entry, state)

    if missing and confidence >= cfg.confidence_threshold:
        needs_clarification = True
        if not question:
            question = _build_missing_fields_question(missing)

    return {
        'missing_fields': missing,
        'clarification_needed': needs_clarification,
        'clarification_question': question,
        'status': 'needs_clarification' if needs_clarification else result_status,
    }


def _check_required_entities(state: IntentGraphState, entry: object) -> list[str]:
    entities = state.get('entities', {})
    missing = []
    for field_name in getattr(entry, 'required_entities', []):
        if field_name not in entities or not entities[field_name]:
            missing.append(field_name)
    return missing


def _build_clarification_question(entry: object, state: IntentGraphState) -> str:
    description = getattr(entry, 'description', '该操作')
    return f'您是想了解{description}吗？请补充更多信息以帮助我准确判断。'


def _build_missing_fields_question(missing: list[str]) -> str:
    field_names = '、'.join(missing)
    return f'请提供以下信息：{field_names}'
