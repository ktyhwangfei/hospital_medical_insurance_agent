import pytest
from pydantic import ValidationError

from src.runtime.intent.models import IntentResult


def test_intent_result_has_required_fields():
    result = IntentResult(
        intent='settlement_exception_guidance',
        confidence=0.9,
        entities={'patient_id': 'P001'},
        citations=['LLM推理'],
        raw_message='结算失败',
    )
    assert result.intent == 'settlement_exception_guidance'
    assert result.confidence == 0.9
    assert result.entities == {'patient_id': 'P001'}
    assert result.citations == ['LLM推理']
    assert result.raw_message == '结算失败'


def test_intent_result_defaults():
    result = IntentResult(
        intent='unknown',
        confidence=0.5,
        raw_message='test',
    )
    assert result.entities == {}
    assert result.citations == []


def test_intent_result_confidence_bounds():
    result = IntentResult(intent='test', confidence=0.0, raw_message='test')
    assert result.confidence == 0.0
    result = IntentResult(intent='test', confidence=1.0, raw_message='test')
    assert result.confidence == 1.0


def test_intent_result_confidence_out_of_bounds():
    with pytest.raises(ValidationError):
        IntentResult(intent='test', confidence=-0.1, raw_message='test')
    with pytest.raises(ValidationError):
        IntentResult(intent='test', confidence=1.1, raw_message='test')


def test_intent_result_model_roundtrip():
    original = IntentResult(
        intent='settlement_exception_guidance',
        confidence=0.9,
        entities={'patient_id': 'P001'},
        citations=['LLM推理'],
        raw_message='结算失败',
    )
    data = original.model_dump()
    restored = IntentResult(**data)
    assert restored == original
