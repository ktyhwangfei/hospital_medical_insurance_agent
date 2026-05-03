from unittest.mock import patch, MagicMock

from src.runtime.intent.service import detect_intent


def test_detect_intent_returns_string():
    with patch('src.runtime.intent.service.parse_intent') as mock_parse:
        mock_result = MagicMock()
        mock_result.intent = 'settlement_exception_guidance'
        mock_parse.return_value = mock_result
        result = detect_intent('结算失败')
        assert isinstance(result, str)
        assert result == 'settlement_exception_guidance'


def test_detect_intent_backward_compat_keywords():
    assert detect_intent('结算失败') == 'settlement_exception_guidance'
    assert detect_intent('医保结算') == 'settlement_exception_guidance'
    assert detect_intent('出院前') == 'pre_discharge_quality_control'
    assert detect_intent('医保风险') == 'pre_discharge_quality_control'
    assert detect_intent('今天天气') == 'unknown'
