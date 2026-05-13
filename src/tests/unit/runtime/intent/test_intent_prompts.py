from src.runtime.intent.prompts import build_intent_prompt
from src.runtime.intent.registry import get_intent_registry


def test_prompt_contains_message():
    registry = get_intent_registry()
    prompt = build_intent_prompt('结算失败', registry)
    assert '结算失败' in prompt


def test_prompt_contains_all_intent_ids():
    registry = get_intent_registry()
    prompt = build_intent_prompt('test', registry)
    for entry in registry:
        assert entry.intent_id in prompt


def test_prompt_contains_intent_descriptions():
    registry = get_intent_registry()
    prompt = build_intent_prompt('test', registry)
    for entry in registry:
        assert entry.description in prompt


def test_prompt_contains_json_format_instruction():
    registry = get_intent_registry()
    prompt = build_intent_prompt('test', registry)
    assert '"intent"' in prompt
    assert '"confidence"' in prompt
    assert '"entities"' in prompt
    assert '"citations"' in prompt
