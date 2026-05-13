import json
import logging

from src.model_service import Message, ModelGateway
from src.runtime.intent.graph.config import IntentGraphConfig
from src.runtime.intent.graph.prompts import build_discrimination_prompt
from src.runtime.intent.graph.state import IntentGraphState
from src.runtime.intent.models import IntentCandidate

logger = logging.getLogger(__name__)


def discrimination(
    state: IntentGraphState,
    config: IntentGraphConfig | None = None,
    gateway: ModelGateway | None = None,
) -> dict:
    cfg = config or IntentGraphConfig()
    candidates = state.get('candidates', [])
    message = state.get('rewritten_message') or state['message']

    if not candidates:
        return _fallback_keyword_result(state)

    top = candidates[0]
    second_score = candidates[1].score if len(candidates) > 1 else 0.0

    if top.score >= cfg.confidence_threshold and (top.score - second_score) >= cfg.gap_threshold:
        return {
            'intent_id': top.intent_id,
            'confidence': top.score,
            'status': 'routed',
            'citations': [f'关键词匹配: {", ".join(top.matched_keywords)}'],
        }

    if not cfg.llm_discrimination_enabled:
        if top.score > 0:
            return {
                'intent_id': top.intent_id,
                'confidence': top.score,
                'status': 'fallback_keyword',
                'citations': ['关键词降级匹配'],
            }
        return _unknown_result(state)

    try:
        return _discriminate_via_llm(state, candidates, message, gateway)
    except Exception:
        logger.warning('intent_llm_discrimination_failed', exc_info=True)
        if top.score > 0:
            return {
                'intent_id': top.intent_id,
                'confidence': top.score * 0.8,
                'status': 'fallback_keyword',
                'citations': ['关键词降级匹配（LLM不可用）'],
            }
        return _unknown_result(state)


def _discriminate_via_llm(
    state: IntentGraphState,
    candidates: list[IntentCandidate],
    message: str,
    gateway: ModelGateway | None,
) -> dict:
    gw = gateway or ModelGateway()
    prompt = build_discrimination_prompt(message, candidates)
    messages = [Message(role='user', content=prompt)]
    response = gw.generate(messages=messages, model_type='llm', scene='intent_recognition')
    return _parse_llm_response(response.content, state)


def _parse_llm_response(content: str, state: IntentGraphState) -> dict:
    try:
        data = json.loads(content)
        intent_id = data.get('intent', 'unknown')
        confidence = float(data.get('confidence', 0.5))
        entities = data.get('entities', {})
        citations = data.get('citations', ['LLM意图推理'])

        return {
            'intent_id': intent_id,
            'confidence': confidence,
            'entities': entities,
            'citations': citations,
            'status': 'routed',
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        return _unknown_result(state)


def _fallback_keyword_result(state: IntentGraphState) -> dict:
    return _unknown_result(state)


def _unknown_result(state: IntentGraphState) -> dict:
    return {
        'intent_id': 'unknown',
        'confidence': 0.0,
        'status': 'unknown',
        'citations': ['无匹配意图'],
    }
