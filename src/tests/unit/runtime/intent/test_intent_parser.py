import json
from unittest.mock import MagicMock, patch

import pytest

from src.model_service.governance_runtime import GovernanceRuntimeError
from src.runtime.intent.models import IntentResult
from src.runtime.intent.parser import parse_intent


def _mock_model_response(content: str):
    mock = MagicMock()
    mock.content = content
    mock.model_name = 'test-model'
    mock.usage = MagicMock(prompt_tokens=10, completion_tokens=20)
    mock.finish_reason = 'stop'
    return mock


@patch('src.runtime.intent.parser.ModelGateway')
def test_parse_intent_via_llm_success(mock_gateway_cls):
    llm_output = json.dumps({
        'intent': 'settlement_exception_guidance',
        'confidence': 0.95,
        'entities': {'patient_id': 'P001'},
        'citations': ['LLM推理'],
    })
    mock_gateway = MagicMock()
    mock_gateway.generate.return_value = _mock_model_response(llm_output)
    mock_gateway_cls.return_value = mock_gateway

    result = parse_intent('张三的医保结算失败了')

    assert isinstance(result, IntentResult)
    assert result.intent == 'settlement_exception_guidance'
    assert result.confidence == 0.95
    assert result.entities.get('patient_id') == 'P001'
    assert result.raw_message == '张三的医保结算失败了'


@patch('src.runtime.intent.parser.ModelGateway')
def test_parse_intent_llm_timeout_fallback(mock_gateway_cls):
    mock_gateway = MagicMock()
    mock_gateway.generate.side_effect = TimeoutError('timeout')
    mock_gateway_cls.return_value = mock_gateway

    result = parse_intent('结算失败')

    assert isinstance(result, IntentResult)
    assert result.intent == 'settlement_exception_guidance'
    assert result.confidence == 0.5
    assert '关键词匹配降级' in result.citations


@patch('src.runtime.intent.parser.ModelGateway')
def test_parse_intent_llm_invalid_json_fallback(mock_gateway_cls):
    mock_gateway = MagicMock()
    mock_gateway.generate.return_value = _mock_model_response('not json')
    mock_gateway_cls.return_value = mock_gateway

    result = parse_intent('结算失败')

    assert isinstance(result, IntentResult)
    assert result.intent == 'settlement_exception_guidance'
    assert result.confidence == 0.5


@patch('src.runtime.intent.parser.ModelGateway')
def test_parse_intent_unknown_intent(mock_gateway_cls):
    llm_output = json.dumps({
        'intent': 'unknown',
        'confidence': 0.3,
        'entities': {},
        'citations': ['无匹配'],
    })
    mock_gateway = MagicMock()
    mock_gateway.generate.return_value = _mock_model_response(llm_output)
    mock_gateway_cls.return_value = mock_gateway

    result = parse_intent('今天天气怎么样')

    assert result.intent == 'unknown'


@patch('src.runtime.intent.parser.ModelGateway')
def test_parse_intent_llm_invalid_intent_id_fallback(mock_gateway_cls):
    llm_output = json.dumps({
        'intent': 'nonexistent_intent',
        'confidence': 0.9,
        'entities': {},
        'citations': ['LLM'],
    })
    mock_gateway = MagicMock()
    mock_gateway.generate.return_value = _mock_model_response(llm_output)
    mock_gateway_cls.return_value = mock_gateway

    result = parse_intent('test')

    assert result.intent == 'unknown'


def test_parse_intent_keyword_fallback_settlement():
    with patch('src.runtime.intent.parser.ModelGateway') as mock_cls:
        mock_cls.side_effect = Exception('model unavailable')
        result = parse_intent('结算失败怎么办')
        assert result.intent == 'settlement_exception_guidance'
        assert result.confidence == 0.5


def test_parse_intent_keyword_fallback_pre_discharge():
    with patch('src.runtime.intent.parser.ModelGateway') as mock_cls:
        mock_cls.side_effect = Exception('model unavailable')
        result = parse_intent('出院前检查')
        assert result.intent == 'pre_discharge_quality_control'
        assert result.confidence == 0.5


def test_parse_intent_keyword_fallback_unknown():
    with patch('src.runtime.intent.parser.ModelGateway') as mock_cls:
        mock_cls.side_effect = Exception('model unavailable')
        result = parse_intent('今天天气')
        assert result.intent == 'unknown'


def test_parse_intent_propagates_governance_runtime_error():
    with patch(
        'src.runtime.intent.parser.build_intent_prompt',
        side_effect=GovernanceRuntimeError('active prompt is corrupt'),
    ):
        with pytest.raises(GovernanceRuntimeError, match='active prompt is corrupt'):
            parse_intent('结算失败怎么办')
