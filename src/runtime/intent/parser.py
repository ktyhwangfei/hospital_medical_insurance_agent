import json
import logging

from src.model_service import Message, ModelGateway
from src.model_service.governance_runtime import GovernanceRuntimeError
from src.runtime.intent.models import IntentResult
from src.runtime.intent.prompts import build_intent_prompt
from src.runtime.intent.registry import get_intent_by_id, get_intent_registry

logger = logging.getLogger(__name__)


def parse_intent(message: str) -> IntentResult:
    try:
        return _parse_via_llm(message)
    except GovernanceRuntimeError:
        raise
    except Exception:
        logger.warning('intent_llm_fallback', exc_info=True)
        return _parse_via_keywords(message)


def _parse_via_llm(message: str) -> IntentResult:
    gateway = ModelGateway()
    registry = get_intent_registry()
    prompt = build_intent_prompt(message, registry)
    messages = [Message(role='user', content=prompt)]
    response = gateway.generate(
        messages=messages,
        model_type='llm',
        scene='intent_recognition',
    )
    return _parse_llm_json(response.content, message)


def _parse_llm_json(content: str, raw_message: str) -> IntentResult:
    try:
        data = json.loads(content)
        intent = data.get('intent', 'unknown')
        if get_intent_by_id(intent) is None and intent != 'unknown':
            intent = 'unknown'
        return IntentResult(
            intent=intent,
            confidence=float(data.get('confidence', 0.5)),
            entities=data.get('entities', {}),
            citations=data.get('citations', []),
            raw_message=raw_message,
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        return _parse_via_keywords(raw_message)


def _parse_via_keywords(message: str) -> IntentResult:
    entries = get_intent_registry()
    best_entry = None
    best_score = 0
    for entry in entries:
        if entry.status != 'active' and entry.intent_id != 'unknown':
            continue
        if not entry.keywords:
            continue
        score = 0
        for kw in entry.keywords:
            if kw in message:
                score += 1
        if score > best_score:
            best_score = score
            best_entry = entry

    if best_entry and best_score > 0:
        return IntentResult(
            intent=best_entry.intent_id,
            confidence=0.5,
            entities={},
            citations=['关键词匹配降级'],
            raw_message=message,
        )
    return IntentResult(
        intent='unknown',
        confidence=0.5,
        entities={},
        citations=['关键词匹配降级'],
        raw_message=message,
    )
