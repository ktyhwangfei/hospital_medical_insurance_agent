import json
import logging

from src.model_service import Message, ModelGateway
from src.runtime.intent.models import IntentResult
from src.runtime.intent.prompts import build_intent_prompt
from src.runtime.intent.registry import get_intent_by_id, get_intent_registry

logger = logging.getLogger(__name__)


def parse_intent(message: str) -> IntentResult:
    try:
        return _parse_via_llm(message)
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
    if '结算失败' in message or '医保结算' in message:
        intent = 'settlement_exception_guidance'
    elif '出院前' in message or '医保风险' in message:
        intent = 'pre_discharge_quality_control'
    else:
        intent = 'unknown'
    return IntentResult(
        intent=intent,
        confidence=0.5,
        entities={},
        citations=['关键词匹配降级'],
        raw_message=message,
    )
