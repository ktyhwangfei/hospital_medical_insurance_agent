from src.runtime.intent.registry import (
    get_intent_by_id,
    get_intent_registry,
)


def test_registry_has_two_intents():
    registry = get_intent_registry()
    assert len(registry) == 2


def test_registry_contains_settlement_intent():
    entry = get_intent_by_id('settlement_exception_guidance')
    assert entry is not None
    assert entry.intent_id == 'settlement_exception_guidance'
    assert entry.priority == 1


def test_registry_contains_pre_discharge_intent():
    entry = get_intent_by_id('pre_discharge_quality_control')
    assert entry is not None
    assert entry.intent_id == 'pre_discharge_quality_control'
    assert entry.priority == 2


def test_registry_returns_none_for_unknown():
    entry = get_intent_by_id('nonexistent_intent')
    assert entry is None


def test_registry_entries_have_examples():
    for entry in get_intent_registry():
        assert len(entry.examples) > 0
        assert all(isinstance(e, str) for e in entry.examples)


def test_registry_priority_ordering():
    registry = get_intent_registry()
    priorities = [e.priority for e in registry]
    assert priorities == sorted(priorities)
