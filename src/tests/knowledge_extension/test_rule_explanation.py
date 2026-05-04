from src.knowledge_extension.rule_explanation.in_memory import InMemoryRuleExplainer
from src.knowledge_extension.rule_explanation.models import RuleExplanationRequest, RuleType


def test_explains_known_settlement_error_code_with_citation():
    explainer = InMemoryRuleExplainer()
    result = explainer.explain(RuleExplanationRequest(rule_type=RuleType.ERROR_CODE, rule_code="E001", scenario="settlement_exception", role="medical_insurance_officer"))

    assert result.status.value == "success"
    assert "错误码" in result.meaning
    assert result.citations


def test_unknown_rule_returns_uncertainty():
    explainer = InMemoryRuleExplainer()
    result = explainer.explain(RuleExplanationRequest(rule_type=RuleType.ERROR_CODE, rule_code="UNKNOWN", scenario="settlement_exception", role="doctor"))

    assert result.status.value == "no_hit"
    assert result.uncertainties


def test_high_impact_rule_requires_human_review():
    explainer = InMemoryRuleExplainer()
    result = explainer.explain(RuleExplanationRequest(rule_type=RuleType.DRG_DIP, rule_code="DRG_LOSS_RISK", scenario="pre_discharge_qc", role="doctor"))

    assert result.requires_human_review is True
    assert "人工" in result.review_hint
    assert "已完成" not in " ".join(result.suggestions)
